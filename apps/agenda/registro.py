from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from apps.atenciones.services import guardar_atencion, resolver_cliente
from apps.auditoria.models import EventoAuditoria
from apps.configuracion.models import ConfiguracionSalon
from apps.integraciones.crypto import ErrorGoogle
from apps.integraciones.google import GoogleCalendar
from apps.integraciones.models import VinculoEventoGoogle
from apps.integraciones.services import encolar_cita, obtener_conexion
from .models import Cita, RegistroServicioAgenda


def url_registro_google(calendario_id, evento_id):
    return reverse("atenciones:nueva") + "?" + urlencode({"calendario": calendario_id, "evento": evento_id})


def datos_cita(cita):
    return {"nombre_cliente": cita.cliente.nombre, "telefono": cita.cliente.telefono, "cliente_id": cita.cliente_id,
            "fecha": timezone.localtime(cita.inicio).date(), "servicio": cita.motivo or ", ".join(cita.servicios_previstos.values_list("nombre", flat=True))}


def registro_existente(*, cita_id=None, usuario_id=None, calendario_id="", evento_id=""):
    filtro = Q(cita_id=cita_id) if cita_id else Q(pk__in=[])
    if evento_id:
        filtro |= Q(usuario_id=usuario_id, calendario_id=calendario_id, evento_id=evento_id)
    return RegistroServicioAgenda.objects.filter(filtro).first()


def preparar_origen(request):
    """GET de solo lectura; el origen del POST queda firmado para esta sesión."""
    if not request.user.has_perm("agenda.view_cita"):
        raise PermissionDenied
    cita, inicial, aviso = None, {}, ""
    if request.GET.get("cita"):
        if not request.GET["cita"].isdigit():
            raise ValidationError("La cita no es válida. Vuelve a la agenda.")
        cita = get_object_or_404(Cita.objects.select_related("cliente"), pk=request.GET["cita"])
        origen = {"tipo": "cita", "cita_id": cita.pk}
        titulo = cita.cliente.nombre
    else:
        if not request.user.has_perm("integraciones.gestionar_google"):
            raise PermissionDenied
        conexion = obtener_conexion(request.user)
        if not conexion or request.GET.get("calendario") != conexion.calendario_id:
            raise ValidationError("El calendario cambió o necesita reconectarse. Vuelve a la agenda.")
        evento_id = request.GET.get("evento", "")
        if not evento_id or len(evento_id) > 1024:
            raise ValidationError("El evento no es válido. Vuelve a la agenda.")
        origen = {"tipo": "google", "calendario_id": conexion.calendario_id, "evento_id": evento_id}
        vinculo = VinculoEventoGoogle.objects.select_related("cita__cliente").filter(conexion=conexion, calendario_id=conexion.calendario_id, evento_id=evento_id).first()
        cita = vinculo.cita if vinculo else None
        existente = registro_existente(cita_id=cita.pk if cita else None, usuario_id=request.user.pk, calendario_id=conexion.calendario_id, evento_id=evento_id)
        if existente:
            return {}, "", "", origen, existente.atencion_id
        adapter = GoogleCalendar(conexion)
        try:
            evento = adapter.obtener_evento(conexion.calendario_id, evento_id)
        finally:
            adapter.close()
        if not evento or evento.get("status") == "cancelled":
            raise ValidationError("Este evento se eliminó o canceló. Actualiza la agenda.")
        try:
            inicio = evento["start"]
            if "dateTime" in inicio:
                valor = datetime.fromisoformat(inicio["dateTime"].replace("Z", "+00:00"))
                if timezone.is_naive(valor):
                    valor = valor.replace(tzinfo=ZoneInfo(inicio["timeZone"]))
                fecha = timezone.localtime(valor).date()
            else:
                fecha = datetime.fromisoformat(inicio["date"]).date()
        except (KeyError, ValueError, TypeError):
            raise ErrorGoogle("No se pudo interpretar la fecha del evento. Revisa la agenda.") from None
        titulo = evento.get("summary") or "Evento sin título"
        inicial = {"nombre_cliente": titulo[:160], "fecha": fecha}
        aviso = "Usamos el título del evento como nombre. Corrígelo si incluye el servicio u otros datos y completa lo que hiciste."
    if cita:
        if not request.user.has_perm("agenda.change_cita"):
            raise PermissionDenied
        existente = registro_existente(cita_id=cita.pk)
        if existente:
            return {}, "", "", origen, existente.atencion_id
        if cita.estado in (Cita.Estado.CANCELADA, Cita.Estado.NO_ASISTIO):
            raise ValidationError("La cita está cancelada o marcada como no asistió. Corrige su estado antes de registrar el servicio.")
        inicial = datos_cita(cita)
        origen.update(cita_id=cita.pk, version=cita.version, cliente_id=cita.cliente_id)
        aviso = "Completa el precio y los materiales de esta visita. Al guardar, la cita quedará marcada como Hecho."
    origen.update(actor=request.user.pk, sesion=request.session.session_key)
    return inicial, titulo, aviso, origen, None


def firmar_origen(origen):
    return signing.dumps(origen, salt="agenda.registrar-servicio", compress=True)


def leer_origen(token, request):
    try:
        origen = signing.loads(token, salt="agenda.registrar-servicio", max_age=1800)
    except signing.BadSignature:
        raise ValidationError("El formulario de la agenda venció o cambió. Abre de nuevo Registrar servicio desde el evento.") from None
    if origen.get("actor") != request.user.pk or origen.get("sesion") != request.session.session_key:
        raise PermissionDenied
    return origen


@transaction.atomic
def guardar_desde_agenda(*, actor, datos, origen, origen_registro="formulario", huella_cliente=None):
    if not all(actor.has_perm(permiso) for permiso in ("agenda.view_cita", "atenciones.add_atencion", "clientes.view_cliente")) or origen.get("actor") != actor.pk:
        raise PermissionDenied
    ConfiguracionSalon.objects.select_for_update().get(pk=1)
    cita = Cita.objects.select_for_update().get(pk=origen["cita_id"]) if origen.get("cita_id") else None
    usuario_id, calendario_id, evento_id = actor.pk, "", ""
    if origen["tipo"] == "google":
        if not actor.has_perm("integraciones.gestionar_google"):
            raise PermissionDenied
        conexion = obtener_conexion(actor)
        if not conexion or conexion.calendario_id != origen["calendario_id"]:
            raise ValidationError("La conexión o el calendario cambió. Vuelve a la agenda antes de guardar.")
        calendario_id, evento_id = origen["calendario_id"], origen["evento_id"]
    elif cita:
        vinculo = VinculoEventoGoogle.objects.select_related("conexion").filter(cita=cita).first()
        if vinculo:
            usuario_id, calendario_id, evento_id = vinculo.conexion.usuario_id, vinculo.calendario_id, vinculo.evento_id
    if cita and not actor.has_perm("agenda.change_cita"):
        raise PermissionDenied
    existente = registro_existente(cita_id=cita.pk if cita else None, usuario_id=usuario_id, calendario_id=calendario_id, evento_id=evento_id)
    if existente:
        return existente.atencion
    if cita:
        if cita.version != origen["version"] or cita.cliente_id != origen["cliente_id"]:
            raise ValidationError("La cita cambió en otra pantalla. Abre de nuevo Registrar servicio desde la agenda.")
        if cita.estado in (Cita.Estado.CANCELADA, Cita.Estado.NO_ASISTIO):
            raise ValidationError("Esta cita está cancelada o marcada como no asistió.")
        elegida = resolver_cliente(datos)
        if not elegida or elegida.pk != cita.cliente_id:
            raise ValidationError("El servicio debe corresponder a la clienta de esta cita. Si es otra persona, corrige primero la cita.")
    atencion = guardar_atencion(actor=actor, datos=datos, origen=origen_registro, huella_cliente=huella_cliente)
    if RegistroServicioAgenda.objects.filter(atencion=atencion).exists():
        raise ValidationError("Este servicio ya está vinculado a otro evento. Abre un nuevo formulario desde la agenda.")
    registro = RegistroServicioAgenda.objects.create(atencion=atencion, cita=cita, usuario_id=usuario_id, calendario_id=calendario_id, evento_id=evento_id)
    if cita:
        cita.estado = Cita.Estado.COMPLETADA
        cita.version += 1
        cita.save(update_fields=["estado", "version"])
        encolar_cita(cita, actor)
    EventoAuditoria.objects.create(actor=actor, origen=origen_registro, operacion="agenda.servicio_registrado", entidad="agenda.RegistroServicioAgenda", entidad_id=str(registro.pk), cambios={"atencion_id": atencion.pk, "cita_id": cita.pk if cita else None, "estado": "hecho"})
    return atencion
