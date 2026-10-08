from django.conf import settings
from django.db import models


class EventoAuditoria(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)
    origen = models.CharField(max_length=16, choices=[("formulario", "Formulario"), ("asistente", "Asistente"), ("sistema", "Sistema")])
    operacion = models.CharField(max_length=80)
    entidad = models.CharField(max_length=80)
    entidad_id = models.CharField(max_length=64)
    cambios = models.JSONField(default=dict)

    class Meta:
        verbose_name = "evento de auditoría"
        verbose_name_plural = "eventos de auditoría"
        ordering = ["-fecha"]
        indexes = [models.Index(fields=["entidad", "entidad_id", "fecha"], name="auditoria_entidad_fecha")]

