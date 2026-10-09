from django.urls import path

from . import views
from . import pwa

app_name = "core"
urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("health/", views.health, name="health"),
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("service-worker.js", pwa.service_worker, name="service_worker"),
    path("sin-conexion/", pwa.offline, name="offline"),
]
