from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.inventario.services import saldo_resultante
from apps.inventario.forms import ProductoForm, ProductoPresentacionForm
from apps.inventario.messages import Label as InventoryLabel, Info as InventoryInfo
from apps.atenciones.services import ClientaAmbigua, resolver_cliente
from apps.atenciones.forms import AtencionForm
from .models import Borrador, Conversacion
from .messages import Error as ProposalError
from .openai_service import ErrorAsistente, conversar
from .services import FORMAS, confirmar, editar_borrador, entidad_actual, guardar_formulario_atencion, token_confirmacion, verificar


class MensajeForm(forms.Form):
    texto = forms.CharField(max_length=4000, label="Tu mensaje", widget=forms.Textarea(attrs={"rows": 3, "class": "form-control", "placeholder": "Hoy atendí a Ana López, teléfono 9991234567: retoque de raíz, cobré $500 y usé tinte 6.0 y peróxido de 20 volúmenes."}))


def conversacion_actual(request):
    if not request.session.session_key:
        request.session.save()
    return Conversacion.objects.get_or_create(usuario=request.user, sesion=request.session.session_key)[0]


@permission_required("asistente.usar_asistente", raise_exception=True)
@require_http_methods(["GET", "POST"])
@never_cache
def chat(request):
    conversacion = conversacion_actual(request)
    form = MensajeForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        anteriores = set(conversacion.borradores.values_list("pk", flat=True))
        try:
            conversar(conversacion=conversacion, texto=form.cleaned_data["texto"])
        except ErrorAsistente as error:
            form.add_error(None, str(error))
        else:
            nuevas = list(conversacion.borradores.filter(tipo__in=["atencion", "producto"], estado="pendiente", vence__gt=timezone.now()).exclude(pk__in=anteriores)[:2])
            if len(nuevas) == 1:
                return redirect("asistente:borrador", pk=nuevas[0].pk)
            return redirect("asistente:chat")
    pendientes = conversacion.borradores.filter(estado="pendiente", vence__gt=timezone.now()).order_by("-creado")[:20]
    historial = list(conversacion.mensajes.order_by("-pk")[:30])[::-1]
    return render(request, "asistente/chat.html", {"form": form, "historial": historial, "borradores": pendientes, "configurado": bool(settings.OPENAI_API_KEY)})


@permission_required("asistente.usar_asistente", raise_exception=True)
@require_http_methods(["GET", "POST"])
@never_cache
def borrador(request, pk):
    borrador = Borrador.objects.select_related("conversacion").filter(pk=pk, conversacion__usuario=request.user, conversacion__sesion=request.session.session_key).first()
    if borrador is None:
        return propuesta_no_disponible(request)
    verificar(borrador, request.user, request.session.session_key, pendiente=False)
    if borrador.estado == "confirmado":
        return redirect(borrador.resultado_url)
    if borrador.tipo == "atencion":
        return formulario_atencion(request, borrador)
    try:
        entidad = entidad_actual(borrador.tipo, borrador.entidad_id)
    except ValidationError:
        return propuesta_no_disponible(request)
    accion = request.POST.get("accion")
    por_presentacion = borrador.tipo == "producto" and bool(borrador.datos.get("presentacion"))
    tipo_form = ProductoPresentacionForm if por_presentacion else FORMAS[borrador.tipo]
    form = tipo_form(request.POST if request.method == "POST" and accion == "editar" else None, initial=borrador.datos, **({"instance": entidad} if borrador.tipo not in ("stock", "atencion") else {}))
    error = ""
    if request.method == "POST":
        try:
            verificar(borrador, request.user, request.session.session_key)
            if accion == "confirmar":
                url = confirmar(borrador_id=pk, actor=request.user, sesion=request.session.session_key, token=request.POST.get("confirmacion", ""))
                messages.success(request, "Confirmaste la propuesta y guardamos el registro.")
                return redirect(url)
            if accion == "editar" and form.is_valid():
                try:
                    version = int(request.POST.get("version_borrador", ""))
                except ValueError:
                    raise ValidationError("Recarga el borrador antes de modificarlo.")
                editar_borrador(borrador_id=pk, actor=request.user, sesion=request.session.session_key, datos=form.cleaned_data, version=version)
                messages.success(request, "Actualizamos la propuesta. Revisa el resumen antes de confirmar.")
                return redirect("asistente:borrador", pk=pk)
            if accion == "descartar":
                Borrador.objects.filter(pk=pk, estado="pendiente").update(estado="descartado")
                messages.success(request, "Descartamos la propuesta.")
                return redirect("asistente:chat")
        except ValidationError as exc:
            error = " ".join(exc.messages)
    resumen = []
    campos = form.fields
    for campo, valor in borrador.datos.items():
        if campo in ("version", "clave_operacion", "clave_alta"):
            continue
        if por_presentacion and campo in ("modo_cantidad", "stock_minimo"):
            continue
        field = campos.get(campo)
        if field is None:
            continue
        if valor is None:
            texto = "Desconocido"
        elif isinstance(valor, bool):
            texto = "Sí" if valor else "No"
        elif campo == "cliente_id":
            texto = str(entidad) if entidad else "Nueva clienta: se creará al confirmar"
        elif hasattr(field, "choices"):
            texto = dict(field.choices).get(valor, valor)
        else:
            texto = valor if valor != "" else "Sin especificar"
        resumen.append((field.label or campo.replace("_", " ").capitalize(), texto))
    saldo = None
    if borrador.tipo == "stock":
        validacion = FORMAS["stock"](borrador.datos)
        if validacion.is_valid():
            try:
                saldo = saldo_resultante(entidad, validacion.cleaned_data)
            except ValidationError as exc:
                error = " ".join(exc.messages)
    disponible = borrador.estado == "pendiente" and borrador.vence > timezone.now()
    stock_inicial = None
    if borrador.tipo == "producto" and entidad is None:
        validacion = ProductoForm(borrador.datos)
        if validacion.is_valid():
            stock_inicial = validacion.cleaned_data.get("stock_inicial_calculado")
    return render(request, "asistente/borrador.html", {"borrador": borrador, "form": form, "resumen": resumen, "entidad": entidad, "saldo": saldo, "confirmacion": token_confirmacion(borrador), "error": error, "disponible": disponible, "stock_inicial": stock_inicial, "inventory_labels": InventoryLabel, "inventory_info": InventoryInfo})


@permission_required("asistente.usar_asistente", raise_exception=True)
@require_http_methods(["GET", "POST"])
@never_cache
def propuesta_no_disponible(request, ruta=None):
    messages.warning(request, ProposalError.ProposalUnavailable)
    return redirect("asistente:chat")


def formulario_atencion(request, borrador):
    accion = request.POST.get("accion")
    form = AtencionForm(request.POST if request.method == "POST" and accion == "guardar" else None, initial=borrador.datos)
    error, coincidencias = "", []
    disponible = borrador.estado == "pendiente" and borrador.vence > timezone.now()
    if request.method == "POST":
        try:
            verificar(borrador, request.user, request.session.session_key)
            if accion == "descartar":
                Borrador.objects.filter(pk=borrador.pk, estado="pendiente").update(estado="descartado")
                return redirect("asistente:chat")
            if accion == "confirmar":
                # Compatibilidad con formularios de revisión abiertos antes del cambio.
                url = confirmar(borrador_id=borrador.pk, actor=request.user, sesion=request.session.session_key, token=request.POST.get("confirmacion", ""))
                messages.success(request, "El servicio quedó guardado en el historial.")
                return redirect(url)
            if accion == "guardar" and form.is_valid():
                try:
                    version = int(request.POST.get("version_borrador", ""))
                except ValueError:
                    raise ValidationError("Recarga el formulario antes de guardar.")
                url = guardar_formulario_atencion(borrador_id=borrador.pk, actor=request.user, sesion=request.session.session_key, token=request.POST.get("confirmacion", ""), datos=form.cleaned_data, version=version)
                messages.success(request, "El servicio quedó guardado en el historial.")
                return redirect(url)
        except ClientaAmbigua as exc:
            coincidencias, error = exc.candidatas, " ".join(exc.messages)
        except ValidationError as exc:
            error = " ".join(exc.messages)
    avisos = list(borrador.avisos)
    datos = form.cleaned_data if form.is_bound and hasattr(form, "cleaned_data") else borrador.datos
    for campo, aviso in [("nombre_cliente", "Falta el nombre de la clienta."), ("servicio", "Falta precisar el servicio realizado."), ("fecha", "Falta la fecha del servicio; elige el día correcto." )]:
        if not datos.get(campo):
            avisos.append(aviso)
    if datos.get("nombre_cliente") and not coincidencias:
        seleccion = datos.get("cliente_id")
        consulta = AtencionForm({**datos, "cliente_id": getattr(seleccion, "pk", seleccion), "clave_operacion": borrador.datos["clave_operacion"], "version": 1})
        consulta.is_valid()
        if "nombre_cliente" in consulta.cleaned_data:
            try:
                resolver_cliente(consulta.cleaned_data)
            except ClientaAmbigua as exc:
                coincidencias = exc.candidatas
            except ValidationError:
                pass
    if coincidencias:
        avisos.append("Hay posibles coincidencias de clientas. Elige la persona correcta o indica que es otra persona.")
    return render(request, "asistente/formulario_atencion.html", {"borrador": borrador, "form": form, "avisos": list(dict.fromkeys(avisos)), "coincidencias": coincidencias, "error": error, "disponible": disponible, "confirmacion": token_confirmacion(borrador)})
