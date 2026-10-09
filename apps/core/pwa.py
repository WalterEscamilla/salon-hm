"""Recursos públicos de instalación, sin datos de clientas ni sesiones."""
from django.contrib.auth.decorators import login_not_required
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_GET


@login_not_required
@require_GET
def manifest(request):
    response = JsonResponse({
        "id": "/",
        "name": "Salón HM",
        "short_name": "Salón HM",
        "description": "Agenda, clientas, servicios y finanzas de Salón HM.",
        "lang": "es-MX",
        "start_url": reverse("core:inicio"),
        "scope": "/",
        "display": "standalone",
        "theme_color": "#873d88",
        "background_color": "#fcf9fc",
        "prefer_related_applications": False,
        "icons": [
            {"src": static("img/pwa/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static("img/pwa/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": static("img/pwa/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }, content_type="application/manifest+json", json_dumps_params={"ensure_ascii": False})
    response["Cache-Control"] = "public, max-age=300"
    return response


@login_not_required
@require_GET
def service_worker(request):
    response = render(request, "core/service-worker.js", content_type="text/javascript; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response


@login_not_required
@require_GET
def offline(request):
    response = render(request, "core/offline.html")
    response["Cache-Control"] = "public, max-age=0, must-revalidate"
    return response
