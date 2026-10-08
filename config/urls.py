from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Administración de Salón HM"
admin.site.site_title = "Salón HM"
admin.site.index_title = "Administración"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("cuenta/", include("apps.cuentas.urls")),
    path("configuracion/", include("apps.configuracion.urls")),
    path("clientes/", include("apps.clientes.urls")),
    path("servicios/", include("apps.catalogos.urls")),
    path("agenda/", include("apps.agenda.urls")),
    path("calendario/", include("apps.integraciones.urls")),
    path("productos/", include("apps.inventario.urls")),
    path("asistente/", include("apps.asistente.urls")),
    path("atenciones/", include("apps.atenciones.urls")),
    path("", include("apps.core.urls")),
]
