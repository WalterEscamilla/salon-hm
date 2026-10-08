from django.contrib.auth.decorators import login_not_required
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.views.decorators.vary import vary_on_headers


@require_GET
@never_cache
@vary_on_headers("HX-Request", "HX-Target")
def inicio(request):
    from apps.agenda.views import limites_dia
    from apps.agenda.queries import citas_en_intervalo
    from apps.integraciones.services import obtener_conexion
    from apps.agenda.lectura_google import combinar, consultar_eventos
    fecha = timezone.localdate()
    inicio_dia, fin_dia = limites_dia(fecha)
    citas = list(citas_en_intervalo(inicio_dia, fin_dia).exclude(estado="cancelada")) if request.user.has_perm("agenda.view_cita") else []
    eventos, error_google = consultar_eventos(request.user, inicio_dia, fin_dia, zona=request.salon.zona_horaria, citas=citas) if request.user.has_perm("agenda.view_cita") else ([], "")
    plantilla = "core/citas_hoy.html" if request.headers.get("HX-Request") == "true" and request.headers.get("HX-Target") == "citas-hoy" else "core/inicio.html"
    return render(request, plantilla, {"fecha_local": fecha, "consulta_agenda": timezone.now(), "citas_hoy": citas, "entradas_hoy": combinar(citas, eventos), "error_google": error_google, "conexion_google": obtener_conexion(request.user)})


@login_not_required
@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        response = JsonResponse({"status": "unavailable"}, status=503)
    else:
        response = JsonResponse({"status": "ok"})
    response["Cache-Control"] = "no-store"
    return response
