from zoneinfo import ZoneInfo

from django.utils import timezone
from django.contrib.auth.middleware import LoginRequiredMiddleware
from django.http import HttpResponse
from django.shortcuts import resolve_url
from django.utils.cache import add_never_cache_headers

from apps.configuracion.queries import obtener_configuracion


class AccesoPrivadoMiddleware(LoginRequiredMiddleware):
    def handle_no_permission(self, request, view_func):
        if request.headers.get("HX-Request") == "true" and request.headers.get("HX-Target") in ("agenda-eventos", "citas-hoy"):
            response = HttpResponse(status=401, headers={"HX-Redirect": resolve_url(self.get_login_url(view_func))})
            add_never_cache_headers(response)
            return response
        return super().handle_no_permission(request, view_func)


class SalonTimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.path != "/health/":
            request.salon = obtener_configuracion()
            with timezone.override(ZoneInfo(request.salon.zona_horaria)):
                return self.get_response(request)
        return self.get_response(request)
