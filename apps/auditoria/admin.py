from django.contrib import admin

from .models import EventoAuditoria


@admin.register(EventoAuditoria)
class EventoAuditoriaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "actor", "operacion", "origen", "entidad", "entidad_id"]
    list_filter = ["origen", "operacion"]
    readonly_fields = ["actor", "fecha", "origen", "operacion", "entidad", "entidad_id", "cambios"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

