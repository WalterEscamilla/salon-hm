from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.decorators.vary import vary_on_headers

from apps.integraciones.crypto import ErrorGoogle
from apps.integraciones.google import GoogleCalendar
from apps.integraciones.models import TrabajoSincronizacion
from apps.integraciones.services import obtener_conexion, sincronizar_cita

from .forms import CitaForm
from .lectura_google import combinar, consultar_eventos
from .models import Cita
from .queries import citas_en_intervalo
from .services import AdvertenciaTraslape, guardar_cita


def limites_dia(dia):
    zona = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(dia, time.min), zona), timezone.make_aware(datetime.combine(dia + timedelta(days=1), time.min), zona)


@permission_required("agenda.view_cita", raise_exception=True)
@require_GET
@never_cache
@vary_on_headers("HX-Request", "HX-Target")
def listado(request):
    try:
        dia = date.fromisoformat(request.GET.get("fecha", ""))
        if not 1900 <= dia.year <= 2200:
            raise ValueError
    except ValueError:
        dia = timezone.localdate()
    vista = request.GET.get("vista", "dia")
    vista = vista if vista in ["dia", "semana", "proximas"] else "dia"
    if vista == "proximas":
        inicio = timezone.now()
        fin = inicio + timedelta(days=30)
        citas = list(Cita.objects.filter(fin__gt=inicio, inicio__lt=fin).exclude(estado=Cita.Estado.CANCELADA).select_related("cliente", "registro_servicio", "evento_google").order_by("inicio")[:100])
        grupos = [{"fecha": None, "citas": citas}]
    else:
        inicio_dia = dia - timedelta(days=dia.weekday()) if vista == "semana" else dia
        cantidad = 7 if vista == "semana" else 1
        inicio, _ = limites_dia(inicio_dia)
        _, fin = limites_dia(inicio_dia + timedelta(days=cantidad - 1))
        citas = list(citas_en_intervalo(inicio, fin))
        grupos = []
        for indice in range(cantidad):
            fecha = inicio_dia + timedelta(days=indice)
            desde, hasta = limites_dia(fecha)
            grupos.append({"fecha": fecha, "citas": [c for c in citas if c.inicio < hasta and c.fin > desde]})
    eventos, error_google = consultar_eventos(request.user, inicio, fin, zona=request.salon.zona_horaria, citas=citas)
    for grupo in grupos:
        if grupo["fecha"]:
            desde, hasta = limites_dia(grupo["fecha"])
            diarios = [evento for evento in eventos if evento["inicio"] < hasta and evento["fin"] > desde]
        else:
            diarios = eventos
        grupo["entradas"] = combinar(grupo["citas"], diarios)
    plantilla = "agenda/eventos.html" if request.headers.get("HX-Request") == "true" and request.headers.get("HX-Target") == "agenda-eventos" else "agenda/listado.html"
    return render(request, plantilla, {"grupos": grupos, "error_google": error_google, "conexion_google": obtener_conexion(request.user), "consulta_agenda": timezone.now(), "dia": dia, "vista": vista, "anterior": dia - timedelta(days=7 if vista == "semana" else 1), "siguiente": dia + timedelta(days=7 if vista == "semana" else 1)})


@require_http_methods(["GET", "POST"])
@never_cache
def editar(request, pk=None):
    permiso = "agenda.change_cita" if pk else "agenda.add_cita"
    if not request.user.has_perm(permiso):
        raise PermissionDenied
    cita = get_object_or_404(Cita.objects.select_related("cliente"), pk=pk) if pk else None
    if cita:
        initial = {"cliente": cita.cliente_id, "motivo": cita.motivo, "inicio": cita.inicio, "fin": cita.fin, "notas": cita.notas, "estado": cita.estado, "servicios": list(cita.servicios_previstos.values_list("servicio_id", flat=True)), "version": cita.version, "clave_operacion": cita.clave_operacion}
    else:
        inicio = timezone.localtime().replace(second=0, microsecond=0) + timedelta(hours=1)
        initial = {"inicio": inicio, "fin": inicio + timedelta(hours=1), "estado": Cita.Estado.PENDIENTE, "cliente": request.GET.get("cliente")}
    form = CitaForm(request.POST if request.method == "POST" else None, initial=initial, cita=cita)
    advertencia = None
    conexion = obtener_conexion(request.user)
    if request.method == "POST" and form.is_valid():
        datos = dict(form.cleaned_data)
        if conexion and datos["estado"] in [Cita.Estado.PENDIENTE, Cita.Estado.CONFIRMADA]:
            adapter = None
            try:
                adapter = GoogleCalendar(conexion)
                evento = getattr(cita, "evento_google", None) if cita else None
                datos["_ocupaciones_google"] = adapter.ocupaciones(datos["inicio"], datos["fin"], excluir_evento=evento.evento_id if evento else None, zona=request.salon.zona_horaria)
            except ErrorGoogle as exc:
                messages.warning(request, "No se comprobó la disponibilidad de Google. " + str(exc))
            except (ValueError, KeyError, TypeError):
                messages.warning(request, "Google devolvió una disponibilidad que no pudimos interpretar. La cita puede guardarse localmente.")
            finally:
                if adapter:
                    adapter.close()
        try:
            guardada = guardar_cita(actor=request.user, datos=datos, sesion=request.session.session_key, cita_id=pk)
        except AdvertenciaTraslape as exc:
            advertencia = exc
            data = form.data.copy()
            data["confirmacion_traslape"] = exc.confirmacion
            data["aceptar_traslape"] = ""
            form = CitaForm(data, initial=initial, cita=cita)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            # El guardado local ya terminó; un error de Google no puede revertirlo.
            sincronizar_cita(guardada, request.user)
            messages.success(request, "La cita quedó guardada en el salón.")
            return redirect("agenda:detalle", pk=guardada.pk)
    return render(request, "agenda/formulario.html", {"form": form, "cita": cita, "advertencia": advertencia, "conexion_google": conexion})


@permission_required("agenda.view_cita", raise_exception=True)
@require_GET
@never_cache
def detalle(request, pk):
    cita = get_object_or_404(Cita.objects.select_related("cliente", "registro_servicio").prefetch_related("servicios_previstos"), pk=pk)
    return render(request, "agenda/detalle.html", {"cita": cita, "conexion_google": obtener_conexion(request.user)})


@permission_required("agenda.change_cita", raise_exception=True)
@require_POST
def sincronizar(request, pk):
    cita = get_object_or_404(Cita, pk=pk)
    trabajo = TrabajoSincronizacion.objects.filter(cita=cita, version=cita.version, conexion__usuario=request.user).first()
    if trabajo and trabajo.estado == TrabajoSincronizacion.Estado.CONFLICTO:
        return redirect("integraciones:resolver", pk=cita.pk)
    if trabajo and not (trabajo.estado == TrabajoSincronizacion.Estado.PROCESANDO and trabajo.bloqueo_hasta and trabajo.bloqueo_hasta > timezone.now()):
        trabajo.estado = TrabajoSincronizacion.Estado.PENDIENTE
        trabajo.proximo_intento = timezone.now()
        trabajo.intentos = 0
        trabajo.save(update_fields=["estado", "proximo_intento", "intentos"])
    if sincronizar_cita(cita, request.user):
        messages.success(request, "La cita está sincronizada con Google.")
    else:
        messages.warning(request, "Revisa el estado de sincronización de la cita.")
    return redirect("agenda:detalle", pk=cita.pk)
