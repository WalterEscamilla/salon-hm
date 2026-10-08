from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q

from apps.auditoria.models import EventoAuditoria
from apps.clientes.identidad import normalizar_nombre, variantes_telefono
from apps.clientes.models import Cliente
from apps.clientes.services import guardar_cliente
from apps.configuracion.models import ConfiguracionSalon
from apps.inventario.services import huella
from .forms import AtencionForm
from .models import Atencion


class ClientaAmbigua(ValidationError):
    def __init__(self, candidatas):
        self.candidatas = list(candidatas)
        super().__init__("Encontramos posibles coincidencias. Elige la clienta correcta o indica que es otra persona.")


def candidatas_cliente(nombre, telefono):
    normalizado = normalizar_nombre(nombre)
    filtro = Q(nombre_normalizado__icontains=normalizado) | Q(nombre__iexact=nombre.strip())
    numeros = variantes_telefono(telefono)
    if numeros:
        filtro |= Q(telefono_normalizado__in=numeros)
    return Cliente.objects.filter(archivado_en__isnull=True).filter(filtro)


def resolver_cliente(datos):
    nombre = datos["nombre_cliente"].strip()
    telefono = datos.get("telefono", "")
    elegida = datos.get("cliente_id")
    if elegida:
        if elegida.archivado_en:
            raise ValidationError("Esta clienta está archivada.")
        return elegida
    candidatas = list(candidatas_cliente(nombre, telefono))
    nombre_normalizado = normalizar_nombre(nombre)
    exactas = [c for c in candidatas if normalizar_nombre(c.nombre) == nombre_normalizado]
    telefonos = variantes_telefono(telefono)
    por_telefono = [c for c in candidatas if c.telefono_normalizado in telefonos]
    if datos.get("crear_nueva"):
        if any(c in exactas for c in por_telefono):
            raise ValidationError("Ya hay una clienta con ese nombre y teléfono. Selecciónala para evitar duplicarla.")
        return None
    if len(por_telefono) == 1 and por_telefono[0] in exactas:
        return por_telefono[0]
    if len(exactas) == 1 and not por_telefono:
        existente = exactas[0]
        if not telefonos or not existente.telefono_normalizado:
            return existente
    if candidatas:
        raise ClientaAmbigua(candidatas)
    return None


def validar_datos(datos):
    datos = {**datos}
    if isinstance(datos.get("cliente_id"), Cliente):
        datos["cliente_id"] = datos["cliente_id"].pk
    form = AtencionForm(datos)
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    return form.cleaned_data


def identidad_borrador(cliente, datos):
    if cliente:
        return huella({"id": cliente.pk, "nombre": cliente.nombre, "telefono": cliente.telefono, "archivado": str(cliente.archivado_en)})
    candidatas = candidatas_cliente(datos["nombre_cliente"], datos["telefono"])
    return huella({"nueva": True, "coincidencias": list(candidatas.values_list("pk", flat=True))})


@transaction.atomic
def guardar_atencion(*, actor, datos, origen="formulario", atencion_id=None, huella_cliente=None):
    if not actor.has_perm("atenciones.change_atencion" if atencion_id else "atenciones.add_atencion") or not actor.has_perm("clientes.view_cliente"):
        raise PermissionDenied
    datos = validar_datos(datos)
    # Serializa la resolución y creación para no duplicar clientas en envíos simultáneos.
    ConfiguracionSalon.objects.select_for_update().get(pk=1)
    # Los registros anteriores conservan su huella cuando no hay nuevos datos financieros.
    contenido = {k: (v.pk if isinstance(v, Cliente) else v) for k, v in datos.items() if k != "version"}
    for campo, vacio in (("costo_materiales", None), ("otros_gastos", None), ("gastos_pagados_en_visita", False)):
        if contenido[campo] == vacio:
            contenido.pop(campo)
    fingerprint = huella(contenido | {"actor": actor.pk})
    if not atencion_id:
        existente = Atencion.objects.filter(clave_operacion=datos["clave_operacion"]).first()
        if existente:
            if existente.huella_operacion != fingerprint:
                raise ValidationError("Esta operación ya se guardó con otros datos.")
            return existente
    atencion = Atencion.objects.select_for_update().get(pk=atencion_id) if atencion_id else Atencion(actor=actor, clave_operacion=datos["clave_operacion"], huella_operacion=fingerprint)
    if atencion_id and datos["version"] != atencion.version:
        raise ValidationError("El servicio cambió en otra ventana. Recarga antes de editarlo.")
    cliente = resolver_cliente(datos)
    if atencion_id:
        registro = getattr(atencion, "registro_agenda", None)
        if registro and registro.cita_id and (not cliente or cliente.pk != registro.cita.cliente_id):
            raise ValidationError("Este servicio pertenece a la clienta de una cita. Conserva esa clienta al corregir el registro.")
    if cliente:
        cliente = Cliente.objects.select_for_update().get(pk=cliente.pk)
    if huella_cliente is not None and identidad_borrador(cliente, datos) != huella_cliente:
        raise ValidationError("Los datos de la clienta cambiaron. Prepara una nueva propuesta para revisar la coincidencia.")
    if cliente is None:
        cliente = guardar_cliente(actor=actor, datos={"nombre": datos["nombre_cliente"], "telefono": datos["telefono"], "notas": ""}, origen=origen)
    elif not cliente.telefono and datos["telefono"]:
        cliente = guardar_cliente(actor=actor, cliente_id=cliente.pk, datos={"nombre": cliente.nombre, "telefono": datos["telefono"], "notas": cliente.notas}, origen=origen)
    atencion.cliente = cliente
    antes = {campo: str(getattr(atencion, campo)) for campo in ("precio_cobrado", "costo_materiales", "otros_gastos", "gastos_pagados_en_visita")}
    for campo in ("fecha", "servicio", "precio_cobrado", "costo_materiales", "otros_gastos", "gastos_pagados_en_visita", "materiales", "notas"):
        setattr(atencion, campo, datos[campo])
    if atencion_id:
        atencion.version += 1
    atencion.full_clean()
    atencion.save()
    despues = {campo: str(getattr(atencion, campo)) for campo in antes}
    EventoAuditoria.objects.create(actor=actor, origen=origen, operacion="atencion.editada" if atencion_id else "atencion.creada", entidad="atenciones.Atencion", entidad_id=str(atencion.pk), cambios={"cliente_id": cliente.pk, "version": atencion.version, "finanzas_antes": antes if atencion_id else {}, "finanzas_despues": despues})
    return atencion
