import uuid

from django.conf import settings
from django.db import models


class Conversacion(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    sesion = models.CharField(max_length=64)
    ocupada_hasta = models.DateTimeField(null=True, blank=True)
    lease = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["usuario", "sesion"], name="asistente_usuario_sesion")]
        permissions = [("usar_asistente", "Puede conversar con el asistente")]


class Mensaje(models.Model):
    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name="mensajes")
    rol = models.CharField(max_length=10, choices=[("user", "Marisol"), ("assistant", "Asistente")])
    texto = models.TextField(max_length=8000)
    contexto = models.JSONField(default=list)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pk"]


class Borrador(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversacion = models.ForeignKey(Conversacion, on_delete=models.PROTECT, related_name="borradores")
    tipo = models.CharField(max_length=12, choices=[("atencion", "Servicio realizado"), ("servicio", "Servicio del catálogo"), ("producto", "Producto"), ("stock", "Movimiento de stock")])
    entidad_id = models.PositiveBigIntegerField(null=True, blank=True)
    datos = models.JSONField()
    avisos = models.JSONField(default=list, blank=True)
    origen_agenda = models.JSONField(default=dict, blank=True)
    huella_entidad = models.CharField(max_length=64, blank=True)
    version = models.PositiveIntegerField(default=1)
    estado = models.CharField(max_length=12, default="pendiente", choices=[("pendiente", "Pendiente"), ("confirmado", "Guardado"), ("descartado", "Descartado")])
    creado = models.DateTimeField(auto_now_add=True)
    vence = models.DateTimeField()
    resultado_url = models.CharField(max_length=200, blank=True)
