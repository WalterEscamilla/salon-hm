import secrets
import time
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required, permission_required
from django.core import signing
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.agenda.models import Cita
from apps.auditoria.models import EventoAuditoria

from .crypto import ErrorGoogle, cifrar
from .google import GoogleCalendar
from .models import ConexionGoogle, TrabajoSincronizacion, VinculoEventoGoogle
from .oauth import configurado, crear_flow
from .services import encolar_cita, procesar_trabajo


@permission_required("integraciones.gestionar_google", raise_exception=True)
@require_GET
@never_cache
def configuracion(request):
    conexion = ConexionGoogle.objects.filter(usuario=request.user, activa=True).first()
    calendarios, error = [], ""
    if conexion and not conexion.requiere_autorizacion:
        adapter = None
        try:
            adapter = GoogleCalendar(conexion)
            calendarios = adapter.calendarios()
        except ErrorGoogle as exc:
            error = str(exc)
        finally:
            if adapter:
                adapter.close()
    return render(request, "integraciones/calendario.html", {"conexion": conexion, "calendarios": calendarios, "error_google": error, "google_configurado": configurado(), "redirect_uri": settings.GOOGLE_REDIRECT_URI})


@permission_required("integraciones.gestionar_google", raise_exception=True)
@require_POST
def conectar(request):
    try:
        state = secrets.token_urlsafe(32)
        flow = crear_flow(state=state)
        url, _ = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="false")
        request.session.pop("google_login", None)
        request.session["google_oauth"] = {"state": state, "verifier": flow.code_verifier, "actor": request.user.pk, "creado": time.time()}
        return redirect(url)
    except ErrorGoogle as exc:
        messages.error(request, str(exc))
        return redirect("integraciones:calendario")


@login_not_required
@require_GET
@never_cache
def retorno(request):
    if request.session.get("google_login"):
        from apps.cuentas.views import retorno_google
        return retorno_google(request)
    return retorno_calendario(request)


@login_required
@permission_required("integraciones.gestionar_google", raise_exception=True)
def retorno_calendario(request):
    context = request.session.get("google_oauth", {})
    valido = context.get("actor") == request.user.pk and time.time() - context.get("creado", 0) < 600 and bool(context.get("state")) and constant_time_compare(request.GET.get("state", ""), context.get("state", ""))
    if not valido:
        messages.error(request, "La autorización venció o no corresponde a tu sesión. Conecta de nuevo.")
        return redirect("integraciones:calendario")
    request.session.pop("google_oauth", None)
    if request.GET.get("error") or not request.GET.get("code"):
        messages.error(request, "Google no fue autorizado. Tus citas locales siguen disponibles.")
        return redirect("integraciones:calendario")
    adapter = None
    try:
        flow = crear_flow(state=context["state"], verifier=context["verifier"])
        flow.fetch_token(code=request.GET["code"], timeout=settings.GOOGLE_HTTP_TIMEOUT)
        credentials = flow.credentials
        granted = credentials.granted_scopes or credentials.scopes or []
        if not set(settings.GOOGLE_OAUTH_SCOPES).issubset(set(granted)):
            raise ErrorGoogle("Faltan permisos de calendario. Conecta de nuevo y autoriza los permisos solicitados.")
        adapter = GoogleCalendar(credentials=credentials)
        calendarios = adapter.calendarios()
        cuenta = next((c["id"] for c in calendarios if c.get("primary")), "")
        if not cuenta:
            raise ErrorGoogle("No pudimos identificar el calendario principal de la cuenta.")
        with transaction.atomic():
            conexion = ConexionGoogle.objects.select_for_update().filter(usuario=request.user).first()
            if conexion and conexion.cuenta and conexion.cuenta != cuenta and VinculoEventoGoogle.objects.filter(conexion=conexion).exists():
                raise ErrorGoogle("Las citas están vinculadas a otra cuenta de Google. Reconecta esa misma cuenta.")
            if not credentials.refresh_token:
                raise ErrorGoogle("Google no entregó autorización para sincronizar después. Revoca el acceso de la aplicación y vuelve a conectar.")
            valores = {"credenciales_cifradas": cifrar(credentials.to_json()), "cuenta": cuenta, "activa": True, "requiere_autorizacion": False}
            conexion, _ = ConexionGoogle.objects.update_or_create(usuario=request.user, defaults=valores)
            EventoAuditoria.objects.create(actor=request.user, origen="formulario", operacion="google.autorizado", entidad="integraciones.ConexionGoogle", entidad_id=str(conexion.pk))
        messages.success(request, "Cuenta autorizada. Ahora elige el calendario de Salón HM.")
    except ErrorGoogle as exc:
        messages.error(request, str(exc))
    except Exception:
        messages.error(request, "No se pudo completar la autorización de Google. Revisa las credenciales y vuelve a conectar.")
    finally:
        if adapter:
            adapter.close()
    response = redirect("integraciones:calendario")
    response["Referrer-Policy"] = "no-referrer"
    return response


@permission_required("integraciones.gestionar_google", raise_exception=True)
@require_POST
def elegir(request):
    conexion = get_object_or_404(ConexionGoogle, usuario=request.user, activa=True, requiere_autorizacion=False)
    adapter = None
    try:
        adapter = GoogleCalendar(conexion)
        calendarios = adapter.calendarios()
        calendario = next((c for c in calendarios if c["id"] == request.POST.get("calendario")), None)
        if not calendario:
            raise ErrorGoogle("Elige un calendario propio de la cuenta conectada.")
        with transaction.atomic():
            conexion = ConexionGoogle.objects.select_for_update().get(pk=conexion.pk)
            if VinculoEventoGoogle.objects.filter(conexion=conexion).exclude(calendario_id=calendario["id"]).exists():
                raise ErrorGoogle("Ya hay citas vinculadas a otro calendario. Conserva ese calendario para evitar duplicados.")
            conexion.calendario_id = calendario["id"]
            conexion.calendario_nombre = calendario.get("summary", "Calendario")[:200]
            conexion.save()
            for cita in Cita.objects.filter(responsable=request.user).exclude(estado=Cita.Estado.CANCELADA):
                encolar_cita(cita, request.user)
            EventoAuditoria.objects.create(actor=request.user, origen="formulario", operacion="google.calendario_elegido", entidad="integraciones.ConexionGoogle", entidad_id=str(conexion.pk))
        messages.success(request, "Calendario elegido. Las citas están listas para sincronizar desde la agenda.")
    except ErrorGoogle as exc:
        messages.error(request, str(exc))
    finally:
        if adapter:
            adapter.close()
    return redirect("integraciones:calendario")


@permission_required("integraciones.gestionar_google", raise_exception=True)
@require_POST
def desconectar(request):
    with transaction.atomic():
        conexion = get_object_or_404(ConexionGoogle.objects.select_for_update(), usuario=request.user)
        conexion.activa = False
        conexion.requiere_autorizacion = True
        conexion.credenciales_cifradas = ""
        conexion.save()
        EventoAuditoria.objects.create(actor=request.user, origen="formulario", operacion="google.desconectado", entidad="integraciones.ConexionGoogle", entidad_id=str(conexion.pk))
    messages.success(request, "Conexión retirada del salón. Las citas locales y los eventos ya publicados se conservan.")
    return redirect("integraciones:calendario")


@permission_required("integraciones.gestionar_google", raise_exception=True)
@require_http_methods(["GET", "POST"])
@never_cache
def resolver(request, pk):
    cita = get_object_or_404(Cita, pk=pk)
    vinculo = get_object_or_404(VinculoEventoGoogle, cita=cita, conexion__usuario=request.user)
    adapter = None
    try:
        adapter = GoogleCalendar(vinculo.conexion)
        actual = adapter.obtener_evento(vinculo.calendario_id, vinculo.evento_id)
        esperado = {"cita": cita.pk, "version": cita.version, "etag": actual.get("etag", "") if actual else "eliminado", "actor": request.user.pk, "sesion": request.session.session_key}
        if request.method == "POST":
            try:
                confirmado = signing.loads(request.POST.get("confirmacion", ""), salt="resolver_google", max_age=600)
            except signing.BadSignature:
                confirmado = None
            if confirmado != esperado:
                raise ErrorGoogle("Las versiones cambiaron o la revisión venció. Revisa de nuevo antes de reemplazar.")
            with transaction.atomic():
                cita = Cita.objects.select_for_update().get(pk=cita.pk)
                if cita.version != esperado["version"]:
                    raise ErrorGoogle("La cita local cambió. Revisa ambas versiones de nuevo.")
                vinculo = VinculoEventoGoogle.objects.select_for_update().get(pk=vinculo.pk)
                viejo_id = vinculo.evento_id
                if not actual or actual.get("status") == "cancelled":
                    vinculo.evento_id = "hm" + uuid.uuid4().hex
                    vinculo.etag = ""
                    vinculo.version_sincronizada = 0
                else:
                    vinculo.etag = actual["etag"]
                vinculo.save()
                trabajo = encolar_cita(cita, request.user)
                if trabajo:
                    if trabajo.estado == TrabajoSincronizacion.Estado.PROCESANDO and trabajo.bloqueo_hasta and trabajo.bloqueo_hasta > timezone.now():
                        raise ErrorGoogle("Hay una sincronización en curso. Revisa de nuevo en unos momentos.")
                    trabajo.estado = TrabajoSincronizacion.Estado.PENDIENTE
                    trabajo.intentos = 0
                    trabajo.proximo_intento = timezone.now()
                    trabajo.save()
                EventoAuditoria.objects.create(actor=request.user, origen="formulario", operacion="google.reemplazo_confirmado", entidad="agenda.Cita", entidad_id=str(cita.pk), cambios={"evento_anterior": viejo_id, "evento_actual": vinculo.evento_id})
            if trabajo:
                procesar_trabajo(trabajo.pk)
            return redirect("agenda:detalle", pk=cita.pk)
        from datetime import datetime
        def fecha_google(parte):
            valor = (parte or {}).get("dateTime")
            return datetime.fromisoformat(valor.replace("Z", "+00:00")) if valor else None
        return render(request, "integraciones/conflicto.html", {"cita": cita, "externo": actual, "inicio_google": fecha_google(actual.get("start")) if actual else None, "fin_google": fecha_google(actual.get("end")) if actual else None, "confirmacion": signing.dumps(esperado, salt="resolver_google")})
    except ErrorGoogle as exc:
        messages.error(request, str(exc))
        return redirect("agenda:detalle", pk=cita.pk)
    finally:
        if adapter:
            adapter.close()
