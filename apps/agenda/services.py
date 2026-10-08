import hashlib
import json

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.auditoria.models import EventoAuditoria
from apps.catalogos.models import Servicio
from apps.clientes.models import Cliente
from apps.configuracion.models import ConfiguracionSalon

from .models import Cita, ServicioPrevisto
from .queries import buscar_traslapes


class AdvertenciaTraslape(Exception):
    def __init__(self, citas, confirmacion, ocupaciones=None):
        self.citas = citas
        self.confirmacion = confirmacion
        self.ocupaciones = ocupaciones or []


def _huella(datos):
    resumen = {"cliente": datos["cliente"].pk, "inicio": datos["inicio"].isoformat(), "fin": datos["fin"].isoformat(), "motivo": datos["motivo"], "notas": datos["notas"], "estado": datos["estado"], "servicios": sorted(s.pk for s in datos["servicios"])}
    return hashlib.sha256(json.dumps(resumen, sort_keys=True).encode()).hexdigest()


@transaction.atomic
def guardar_cita(*, actor, datos, sesion, cita_id=None):
    permiso = "agenda.change_cita" if cita_id else "agenda.add_cita"
    if not actor.has_perm(permiso):
        raise PermissionDenied
    if timezone.is_naive(datos["inicio"]) or timezone.is_naive(datos["fin"]):
        raise ValidationError("El horario requiere una zona horaria válida.")
    if datos["fin"] <= datos["inicio"]:
        raise ValidationError("El fin debe ser posterior al inicio.")
    if datos["estado"] not in Cita.Estado.values:
        raise ValidationError("Estado de cita inválido.")
    if not datos["motivo"].strip() and not datos["servicios"]:
        raise ValidationError("Indica un servicio previsto.")
    # Un solo salón: serializa la revisión y escritura de horarios para evitar carreras.
    ConfiguracionSalon.objects.select_for_update().get(pk=1)
    huella = _huella(datos)
    if not cita_id:
        repetida = Cita.objects.filter(clave_operacion=datos["clave_operacion"]).first()
        if repetida:
            if repetida.responsable_id != actor.pk or repetida.hash_operacion != huella:
                raise ValidationError("La operación ya fue utilizada con otros datos. Abre una nueva cita.")
            return repetida
    cita = Cita.objects.select_for_update().get(pk=cita_id) if cita_id else Cita(responsable=actor, clave_operacion=datos["clave_operacion"], hash_operacion=huella)
    if cita_id and cita.version != datos.get("version"):
        raise ValidationError("La cita cambió en otra pantalla. Recarga antes de guardar.")
    cliente = Cliente.objects.get(pk=datos["cliente"].pk)
    registro = getattr(cita, "registro_servicio", None) if cita_id else None
    if registro and (datos["estado"] != Cita.Estado.COMPLETADA or cliente.pk != cita.cliente_id):
        raise ValidationError("Esta cita ya tiene un servicio registrado. Conserva su clienta y el estado Completada; puedes corregir la atención desde Ver servicio.")
    if cliente.archivado_en and (not cita_id or cita.cliente_id != cliente.pk):
        raise ValidationError("Selecciona una clienta activa.")
    servicios = list(Servicio.objects.filter(pk__in=[s.pk for s in datos["servicios"]]))
    permitidos = set(cita.servicios_previstos.values_list("servicio_id", flat=True)) if cita_id else set()
    if len(servicios) != len(datos["servicios"]) or any(not s.activo and s.pk not in permitidos for s in servicios):
        raise ValidationError("Uno de los servicios ya no está disponible.")
    traslapes = buscar_traslapes(datos["inicio"], datos["fin"], excluir=cita_id) if datos["estado"] in [Cita.Estado.PENDIENTE, Cita.Estado.CONFIRMADA] else []
    ocupaciones = datos.get("_ocupaciones_google", []) if datos["estado"] in [Cita.Estado.PENDIENTE, Cita.Estado.CONFIRMADA] else []
    if traslapes or ocupaciones:
        esperado = {"huella": huella, "actor": actor.pk, "sesion": sesion, "citas": [(c.pk, c.version) for c in traslapes], "google": ocupaciones}
        # JSON convierte tuplas a listas.
        esperado["citas"] = [list(c) for c in esperado["citas"]]
        valido = False
        if datos.get("aceptar_traslape") and datos.get("confirmacion_traslape"):
            try:
                valido = signing.loads(datos["confirmacion_traslape"], salt="traslape", max_age=600) == esperado
            except signing.BadSignature:
                pass
        if not valido:
            raise AdvertenciaTraslape(traslapes, signing.dumps(esperado, salt="traslape"), ocupaciones)
    cita.cliente = cliente
    for campo in ("motivo", "inicio", "fin", "notas", "estado"):
        setattr(cita, campo, datos[campo])
    if cita_id:
        cita.version += 1
    cita.full_clean()
    cita.save()
    anteriores = {s.servicio_id: s for s in cita.servicios_previstos.all()}
    seleccionados = {s.pk for s in servicios}
    cita.servicios_previstos.exclude(servicio_id__in=seleccionados).delete()
    for servicio in servicios:
        if servicio.pk not in anteriores:
            ServicioPrevisto.objects.create(cita=cita, servicio=servicio, nombre=servicio.nombre, duracion_minutos=servicio.duracion_minutos)
    EventoAuditoria.objects.create(actor=actor, origen="formulario", operacion="cita.editada" if cita_id else "cita.creada", entidad="agenda.Cita", entidad_id=str(cita.pk), cambios={"version": cita.version, "estado": cita.estado, "traslape_aceptado": bool(traslapes or ocupaciones)})
    from apps.integraciones.services import encolar_cita
    encolar_cita(cita, actor)
    return cita
