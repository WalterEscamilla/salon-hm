import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.views.decorators.vary import vary_on_headers
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.agenda.registro import firmar_origen, guardar_desde_agenda, leer_origen, preparar_origen
from apps.integraciones.crypto import ErrorGoogle
from apps.asistente.formularios import avisos_atencion
from apps.asistente.models import Borrador, Conversacion
from apps.asistente.openai_service import ErrorAsistente, conversar
from apps.asistente.services import guardar_formulario_atencion, token_confirmacion, verificar
from apps.inventario.services import serializar
from .forms import AtencionForm, AtencionPropuestaForm, DescripcionServicioForm
from .models import Atencion
from .services import ClientaAmbigua, guardar_atencion


@permission_required(["atenciones.view_atencion", "clientes.view_cliente"], raise_exception=True)
@never_cache
def listado(request):
    consulta = request.GET.get("q", "").strip()[:160]
    atenciones = Atencion.objects.select_related("cliente")
    if consulta:
        from django.db.models import Q
        atenciones = atenciones.filter(Q(cliente__nombre__icontains=consulta) | Q(servicio__icontains=consulta) | Q(cliente__telefono__icontains=consulta))
    return render(request, "atenciones/listado.html", {"atenciones": Paginator(atenciones, 30).get_page(request.GET.get("page")), "consulta": consulta})


@permission_required(["atenciones.view_atencion", "clientes.view_cliente"], raise_exception=True)
@never_cache
def detalle(request, pk):
    atencion = get_object_or_404(Atencion.objects.select_related("cliente"), pk=pk)
    from django.db.models import Q
    anterior = atencion.cliente.atenciones.filter(Q(fecha__lt=atencion.fecha) | Q(fecha=atencion.fecha, creado_en__lt=atencion.creado_en)).first()
    return render(request, "atenciones/detalle.html", {"atencion": atencion, "anterior": anterior})


@require_http_methods(["GET", "POST"])
@never_cache
@vary_on_headers("HX-Request", "HX-Target")
def editar(request, pk=None):
    if not request.user.has_perm("atenciones.change_atencion" if pk else "atenciones.add_atencion") or not request.user.has_perm("clientes.view_cliente"):
        raise PermissionDenied
    atencion = get_object_or_404(Atencion.objects.select_related("cliente"), pk=pk) if pk else None
    inicial = {}
    accion = request.POST.get("accion", "guardar")
    borrador, respuesta_asistente, error_asistente, avisos = None, "", "", []
    referencia = (request.POST.get("borrador_asistente") or request.GET.get("borrador")) if not pk else None
    if referencia:
        try:
            identificador = uuid.UUID(referencia)
        except ValueError:
            raise Http404 from None
        borrador = get_object_or_404(Borrador.objects.select_related("conversacion"), pk=identificador, tipo="atencion", conversacion__usuario=request.user, conversacion__sesion=request.session.session_key)
        verificar(borrador, request.user, request.session.session_key, pendiente=False)
        if borrador.estado == "confirmado":
            return redirect(borrador.resultado_url)
        inicial = dict(borrador.datos)
        if borrador.estado != "pendiente" or borrador.vence <= timezone.now():
            error_asistente = "Este formulario venció o se descartó. Interpreta de nuevo tu descripción antes de guardar."
    origen, origen_token, evento_titulo, aviso_agenda, error_agenda = None, "", "", "", ""
    if atencion:
        inicial = {campo: getattr(atencion, campo) for campo in ("fecha", "servicio", "precio_cobrado", "costo_materiales", "otros_gastos", "gastos_pagados_en_visita", "materiales", "notas", "version", "clave_operacion")}
        inicial.update(nombre_cliente=atencion.cliente.nombre, telefono=atencion.cliente.telefono, cliente_id=atencion.cliente_id)
    elif not borrador and request.GET.get("cliente", "").isdigit():
        cliente = get_object_or_404(Cliente, pk=request.GET["cliente"], archivado_en__isnull=True)
        inicial.update(nombre_cliente=cliente.nombre, telefono=cliente.telefono, cliente_id=cliente.pk)
    if borrador and borrador.origen_agenda:
        origen = borrador.origen_agenda
        origen_token = firmar_origen(origen)
        evento_titulo = borrador.datos.get("nombre_cliente", "")
        aviso_agenda = "Este formulario está vinculado al evento. Al guardar el servicio, quedará marcado como Hecho en la agenda."
    elif not pk and request.method == "GET" and (request.GET.get("cita") or request.GET.get("evento")):
        try:
            inicial, evento_titulo, aviso_agenda, origen, registrada = preparar_origen(request)
            if registrada:
                return redirect("atenciones:detalle", pk=registrada)
            origen_token = firmar_origen(origen)
        except (ValidationError, ErrorGoogle) as error:
            error_agenda = " ".join(error.messages) if isinstance(error, ValidationError) else str(error)
    elif not pk and request.method == "POST" and (request.POST.get("origen_agenda") or request.GET.get("cita") or request.GET.get("evento")):
        origen_token = request.POST.get("origen_agenda", "")
        try:
            origen = leer_origen(origen_token, request)
        except ValidationError as error:
            error_agenda = " ".join(error.messages)
    if request.method == "POST" and accion == "interpretar":
        inicial = {campo: request.POST.get(campo, "") for campo in AtencionForm.base_fields}
    form = AtencionForm(request.POST if request.method == "POST" and accion == "guardar" else None, initial=inicial)
    asistente_form = DescripcionServicioForm(request.POST if request.method == "POST" and accion == "interpretar" else None, initial={"texto_asistente": request.POST.get("texto_asistente", "")})
    coincidencias = []
    if request.method == "POST" and accion == "interpretar" and not pk and not error_agenda:
        if not request.user.has_perm("asistente.usar_asistente"):
            raise PermissionDenied
        if asistente_form.is_valid():
            if not request.session.session_key:
                request.session.save()
            conv, _ = Conversacion.objects.get_or_create(usuario=request.user, sesion=request.session.session_key)
            anteriores = set(conv.borradores.values_list("pk", flat=True))
            propuesta = AtencionPropuestaForm(request.POST)
            propuesta.is_valid()
            contexto = {campo: valor.isoformat() if hasattr(valor, "isoformat") else getattr(valor, "pk", valor) for campo, valor in propuesta.cleaned_data.items() if campo not in ("clave_operacion", "version")}
            try:
                respuesta_asistente = conversar(conversacion=conv, texto=asistente_form.cleaned_data["texto_asistente"], formulario=serializar(contexto), origen_agenda=origen)
            except ErrorAsistente as error:
                error_asistente = str(error)
            else:
                nuevo = conv.borradores.filter(tipo="atencion", estado="pendiente", vence__gt=timezone.now()).exclude(pk__in=anteriores).order_by("-creado").first()
                if nuevo:
                    if borrador:
                        Borrador.objects.filter(pk=borrador.pk, estado="pendiente").update(estado="descartado")
                    borrador = nuevo
                    form = AtencionForm(initial=borrador.datos)
                    error_asistente = ""
                    avisos, coincidencias = avisos_atencion(borrador.datos, borrador.avisos)
    elif request.method == "POST" and accion == "guardar" and not error_agenda and form.is_valid():
        try:
            if borrador:
                if (origen or {}) != borrador.origen_agenda:
                    raise ValidationError("El formulario no corresponde a este evento. Interpreta de nuevo la descripción.")
                try:
                    version = int(request.POST.get("version_borrador", ""))
                except ValueError:
                    raise ValidationError("Recarga el formulario antes de guardar.") from None
                url = guardar_formulario_atencion(borrador_id=borrador.pk, actor=request.user, sesion=request.session.session_key, token=request.POST.get("confirmacion", ""), datos=form.cleaned_data, version=version)
                messages.success(request, "Guardamos el servicio y el evento quedó marcado como Hecho en la agenda." if origen else "Guardamos el servicio en el historial de la clienta.")
                return redirect(url)
            atencion = guardar_desde_agenda(actor=request.user, datos=form.cleaned_data, origen=origen) if origen else guardar_atencion(actor=request.user, datos=form.cleaned_data, atencion_id=pk)
        except ClientaAmbigua as error:
            coincidencias = error.candidatas
            form.add_error(None, error)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Guardamos el servicio y el evento quedó marcado como Hecho en la agenda." if origen else "Guardamos el servicio en el historial de la clienta.")
            return redirect("atenciones:detalle", pk=atencion.pk)
    if borrador and not avisos:
        datos = form.cleaned_data if form.is_bound and hasattr(form, "cleaned_data") else form.initial
        avisos, posibles = avisos_atencion(datos, borrador.avisos)
        coincidencias = coincidencias or posibles
    if borrador and borrador.origen_agenda:
        evento_titulo = borrador.datos.get("nombre_cliente") or "Evento vinculado"
        aviso_agenda = "Este formulario está vinculado al evento. Al guardar el servicio, quedará marcado como Hecho en la agenda."
    contexto = {"form": form, "coincidencias": coincidencias, "titulo": "Editar servicio realizado" if pk else "Registrar servicio realizado", "origen_agenda": origen_token, "evento_titulo": evento_titulo, "aviso_agenda": aviso_agenda, "error_agenda": error_agenda, "desde_agenda": bool(origen_token or request.GET.get("cita") or request.GET.get("evento")), "asistente_form": asistente_form, "mostrar_asistente": not pk and request.user.has_perm("asistente.usar_asistente"), "asistente_configurado": bool(settings.OPENAI_API_KEY), "respuesta_asistente": respuesta_asistente, "error_asistente": error_asistente, "avisos": avisos, "borrador_asistente": borrador, "confirmacion": token_confirmacion(borrador) if borrador else ""}
    plantilla = "atenciones/registro.html" if request.headers.get("HX-Request") == "true" and request.headers.get("HX-Target") == "registro-servicio" else "atenciones/formulario.html"
    return render(request, plantilla, contexto)
