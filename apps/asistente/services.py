from datetime import timedelta
import uuid

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.auditoria.models import EventoAuditoria
from apps.atenciones.forms import AtencionForm, AtencionPropuestaForm
from apps.atenciones.services import ClientaAmbigua, guardar_atencion, identidad_borrador, resolver_cliente
from apps.clientes.models import Cliente
from apps.catalogos.forms import ServicioForm
from apps.catalogos.models import Servicio
from apps.catalogos.services import guardar_servicio
from apps.inventario.forms import MovimientoForm, ProductoForm
from apps.inventario.models import Producto
from apps.inventario.services import guardar_producto, huella, registrar_movimiento, saldo_resultante, serializar
from .models import Borrador

FORMAS = {"servicio": ServicioForm, "producto": ProductoForm, "stock": MovimientoForm, "atencion": AtencionForm}
MODELOS = {"servicio": Servicio, "producto": Producto, "stock": Producto, "atencion": Cliente}


def permiso(actor, tipo, entidad_id):
    if tipo == "atencion":
        if not actor.has_perm("asistente.usar_asistente") or not actor.has_perm("atenciones.add_atencion") or not actor.has_perm("clientes.view_cliente"):
            raise PermissionDenied
        return
    nombre = "inventario.add_movimientostock" if tipo == "stock" else f"{'catalogos' if tipo == 'servicio' else 'inventario'}.{'change' if entidad_id else 'add'}_{tipo}"
    if not actor.has_perm("asistente.usar_asistente") or not actor.has_perm(nombre):
        raise PermissionDenied


def datos_entidad(tipo, entidad):
    if tipo == "stock":
        return {"id": entidad.pk, "version": entidad.version, "unidad": entidad.unidad, "existencias": str(entidad.existencias)}
    datos = {campo: getattr(entidad, campo) for campo in FORMAS[tipo]().fields}
    if tipo == "producto":
        datos["version"] = entidad.version
    return serializar(datos)


def entidad_actual(tipo, entidad_id, bloquear=False):
    if not entidad_id:
        return None
    qs = MODELOS[tipo].objects
    if bloquear:
        qs = qs.select_for_update()
    try:
        return qs.get(pk=entidad_id)
    except MODELOS[tipo].DoesNotExist:
        raise ValidationError("El registro ya no existe. Busca nuevamente.")


def validar(tipo, datos, entidad=None):
    form = FORMAS[tipo](datos, **({"instance": entidad} if tipo not in ("stock", "atencion") else {}))
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    if tipo == "stock":
        if entidad is None:
            raise ValidationError("Elige el producto antes de preparar stock.")
        if entidad.version != form.cleaned_data["version"]:
            raise ValidationError("El stock cambió. Busca nuevamente el producto.")
        saldo_resultante(entidad, form.cleaned_data)
    return form


def normalizar_atencion(actor, datos, *, permitir_incompleto=False):
    datos = dict(datos)
    if isinstance(datos.get("cliente_id"), Cliente):
        datos["cliente_id"] = datos["cliente_id"].pk
    if permitir_incompleto:
        form = AtencionPropuestaForm(datos)
        if not form.is_valid():
            raise ValidationError(form.errors.as_text())
    else:
        form = validar("atencion", datos)
    limpios = form.cleaned_data
    ambiguo = False
    try:
        cliente = resolver_cliente(limpios) if limpios["nombre_cliente"] or limpios["cliente_id"] else None
    except ClientaAmbigua:
        if not permitir_incompleto:
            raise
        cliente, ambiguo = None, True
    if cliente is None and not actor.has_perm("clientes.add_cliente"):
        raise PermissionDenied
    fingerprint = identidad_borrador(cliente, limpios) if not ambiguo and (cliente or limpios["nombre_cliente"]) else ""
    if cliente:
        limpios["cliente_id"] = cliente.pk
        limpios["nombre_cliente"] = cliente.nombre
        limpios["telefono"] = cliente.telefono or limpios["telefono"]
    else:
        limpios["cliente_id"] = None
    guardados = serializar(limpios)
    guardados["fecha"] = limpios["fecha"].isoformat() if limpios["fecha"] else None
    guardados["clave_operacion"] = str(limpios["clave_operacion"])
    return guardados, cliente.pk if cliente else None, fingerprint


@transaction.atomic
def preparar(*, conversacion, tipo, entidad_id, datos, avisos=(), permitir_incompleto=False, origen_agenda=None):
    if tipo not in FORMAS:
        raise ValidationError("Operación no disponible.")
    actor = conversacion.usuario
    permiso(actor, tipo, entidad_id)
    if tipo == "atencion":
        from apps.configuracion.models import ConfiguracionSalon
        ConfiguracionSalon.objects.select_for_update().get(pk=1)
        datos = {**datos, "clave_operacion": str(uuid.uuid4()), "version": 1}
        guardados, entidad_id, fingerprint = normalizar_atencion(actor, datos, permitir_incompleto=permitir_incompleto)
    else:
        entidad = entidad_actual(tipo, entidad_id, bloquear=True)
        fingerprint = huella(datos_entidad(tipo, entidad)) if entidad else ""
        if tipo == "stock":
            datos = {**datos, "version": entidad.version, "clave_operacion": str(uuid.uuid4())}
        form = validar(tipo, datos, entidad)
        guardados = serializar(form.cleaned_data)
        if tipo == "stock":
            guardados["clave_operacion"] = str(guardados["clave_operacion"])
    borrador = Borrador.objects.create(conversacion=conversacion, tipo=tipo, entidad_id=entidad_id, datos=guardados, avisos=list(avisos), origen_agenda=origen_agenda or {}, huella_entidad=fingerprint, vence=timezone.now() + timedelta(minutes=30))
    EventoAuditoria.objects.create(actor=actor, origen="asistente", operacion="borrador.preparado", entidad="asistente.Borrador", entidad_id=str(borrador.pk))
    return borrador


def verificar(borrador, actor, sesion, pendiente=True):
    if borrador.conversacion.usuario_id != actor.pk or borrador.conversacion.sesion != sesion:
        raise PermissionDenied
    permiso(actor, borrador.tipo, borrador.entidad_id)
    if pendiente and (borrador.estado != "pendiente" or borrador.vence <= timezone.now()):
        raise ValidationError("El borrador ya se guardó, se descartó o venció. Prepara uno nuevo.")


def token_confirmacion(borrador):
    return signing.dumps(datos_confirmacion(borrador), salt="asistente.confirmar")


def datos_confirmacion(borrador):
    datos = {"id": str(borrador.pk), "version": borrador.version, "datos": huella(borrador.datos), "actor": borrador.conversacion.usuario_id, "sesion": borrador.conversacion.sesion}
    if borrador.origen_agenda:
        datos["agenda"] = huella(borrador.origen_agenda)
    return datos


@transaction.atomic
def editar_borrador(*, borrador_id, actor, sesion, datos, version):
    borrador = Borrador.objects.select_for_update().select_related("conversacion").get(pk=borrador_id)
    verificar(borrador, actor, sesion)
    if borrador.version != version:
        raise ValidationError("El borrador cambió en otra ventana. Recarga para revisarlo.")
    if borrador.tipo == "atencion":
        datos = {**datos, "clave_operacion": borrador.datos["clave_operacion"]}
        borrador.datos, borrador.entidad_id, borrador.huella_entidad = normalizar_atencion(actor, datos)
    else:
        entidad = entidad_actual(borrador.tipo, borrador.entidad_id, bloquear=True)
        fingerprint = huella(datos_entidad(borrador.tipo, entidad)) if entidad else ""
        if fingerprint != borrador.huella_entidad:
            raise ValidationError("El registro cambió desde la propuesta. Prepara un nuevo borrador con los datos actuales.")
        form = validar(borrador.tipo, datos, entidad)
        borrador.datos = serializar(form.cleaned_data)
        if borrador.tipo == "stock":
            # La clave pertenece al servidor: no se acepta una enviada por el navegador.
            borrador.datos["clave_operacion"] = str(uuid.uuid4())
    borrador.version += 1
    borrador.save(update_fields=["datos", "version", "entidad_id", "huella_entidad"])
    return borrador


@transaction.atomic
def confirmar(*, borrador_id, actor, sesion, token):
    borrador = Borrador.objects.select_for_update().select_related("conversacion").get(pk=borrador_id)
    verificar(borrador, actor, sesion, pendiente=False)
    try:
        firmado = signing.loads(token, salt="asistente.confirmar", max_age=1800)
    except signing.BadSignature:
        raise ValidationError("La confirmación venció. Abre nuevamente el borrador.")
    esperado = datos_confirmacion(borrador)
    if firmado != esperado:
        raise ValidationError("La propuesta cambió. Revisa los datos y vuelve a confirmar.")
    if borrador.estado == "confirmado":
        return borrador.resultado_url
    verificar(borrador, actor, sesion)
    entidad = entidad_actual(borrador.tipo, borrador.entidad_id, bloquear=borrador.tipo != "atencion")
    if borrador.tipo != "atencion":
        fingerprint = huella(datos_entidad(borrador.tipo, entidad)) if entidad else ""
        if fingerprint != borrador.huella_entidad:
            raise ValidationError("El registro o el stock cambiaron. Prepara un nuevo borrador para revisar el saldo actual.")
    form = validar(borrador.tipo, borrador.datos, entidad)
    if borrador.tipo == "atencion":
        if borrador.origen_agenda:
            from apps.agenda.registro import guardar_desde_agenda
            atencion = guardar_desde_agenda(actor=actor, datos=form.cleaned_data, origen=borrador.origen_agenda, origen_registro="asistente", huella_cliente=borrador.huella_entidad)
            url = reverse("atenciones:detalle", args=[atencion.pk])
        else:
            atencion = guardar_atencion(actor=actor, datos=form.cleaned_data, origen="asistente", huella_cliente=borrador.huella_entidad)
            url = reverse("clientes:detalle", args=[atencion.cliente_id])
    elif borrador.tipo == "servicio":
        guardar_servicio(actor=actor, datos=form.cleaned_data, servicio_id=borrador.entidad_id, origen="asistente")
        url = reverse("catalogos:listado")
    elif borrador.tipo == "producto":
        producto = guardar_producto(actor=actor, datos=form.cleaned_data, producto_id=borrador.entidad_id, origen="asistente")
        url = reverse("inventario:detalle", args=[producto.pk])
    else:
        registrar_movimiento(actor=actor, producto_id=borrador.entidad_id, datos=form.cleaned_data, origen="asistente")
        url = reverse("inventario:detalle", args=[borrador.entidad_id])
    borrador.estado = "confirmado"
    borrador.resultado_url = url
    borrador.save(update_fields=["estado", "resultado_url"])
    EventoAuditoria.objects.create(actor=actor, origen="asistente", operacion="borrador.confirmado", entidad="asistente.Borrador", entidad_id=str(borrador.pk), cambios={"version": borrador.version, "huella": huella(borrador.datos)})
    return url


@transaction.atomic
def guardar_formulario_atencion(*, borrador_id, actor, sesion, token, datos, version):
    borrador = Borrador.objects.select_for_update().select_related("conversacion").get(pk=borrador_id)
    verificar(borrador, actor, sesion, pendiente=False)
    if borrador.tipo != "atencion":
        raise ValidationError("Este formulario solo registra servicios realizados.")
    try:
        firmado = signing.loads(token, salt="asistente.confirmar", max_age=1800)
    except signing.BadSignature:
        raise ValidationError("El formulario venció. Ábrelo de nuevo antes de guardar.")
    esperado = datos_confirmacion(borrador)
    if firmado != esperado or version != borrador.version:
        raise ValidationError("El formulario cambió en otra ventana. Recarga antes de guardar.")
    if borrador.estado == "confirmado":
        return borrador.resultado_url
    verificar(borrador, actor, sesion)
    from apps.configuracion.models import ConfiguracionSalon
    ConfiguracionSalon.objects.select_for_update().get(pk=1)
    datos = {**datos, "clave_operacion": borrador.datos["clave_operacion"], "version": 1}
    campos_identidad = ("nombre_cliente", "telefono", "cliente_id", "crear_nueva")
    identidad_enviada = {campo: datos[campo].pk if isinstance(datos[campo], Cliente) else datos[campo] for campo in campos_identidad}
    identidad_original = {campo: borrador.datos.get(campo) for campo in campos_identidad}
    # Conserva la comprobación de identidad si Marisol solo modificó el servicio.
    fingerprint = borrador.huella_entidad if identidad_enviada == identidad_original and borrador.huella_entidad else None
    if borrador.origen_agenda:
        from apps.agenda.registro import guardar_desde_agenda
        atencion = guardar_desde_agenda(actor=actor, datos=datos, origen=borrador.origen_agenda, origen_registro="asistente", huella_cliente=fingerprint)
        url = reverse("atenciones:detalle", args=[atencion.pk])
    else:
        atencion = guardar_atencion(actor=actor, datos=datos, origen="asistente", huella_cliente=fingerprint)
        url = reverse("clientes:detalle", args=[atencion.cliente_id])
    borrador.estado, borrador.resultado_url = "confirmado", url
    borrador.save(update_fields=["estado", "resultado_url"])
    # El borrador conserva la interpretación original; la visita guarda lo aprobado.
    EventoAuditoria.objects.create(actor=actor, origen="asistente", operacion="borrador.confirmado", entidad="asistente.Borrador", entidad_id=str(borrador.pk), cambios={"version": borrador.version, "huella": huella({k: v.pk if isinstance(v, Cliente) else v for k, v in datos.items()}), "atencion_id": atencion.pk, "aprobacion": "formulario"})
    return url
