from django.conf import settings
from django.db import models


class ConexionGoogle(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    credenciales_cifradas = models.TextField()
    cuenta = models.CharField(max_length=320, blank=True)
    calendario_id = models.CharField(max_length=320, blank=True)
    calendario_nombre = models.CharField(max_length=200, blank=True)
    activa = models.BooleanField(default=True)
    requiere_autorizacion = models.BooleanField(default=False)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = [("gestionar_google", "Puede conectar y gestionar Google Calendar")]


class VinculoEventoGoogle(models.Model):
    cita = models.OneToOneField("agenda.Cita", on_delete=models.PROTECT, related_name="evento_google")
    conexion = models.ForeignKey(ConexionGoogle, on_delete=models.PROTECT)
    calendario_id = models.CharField(max_length=320)
    evento_id = models.CharField(max_length=100)
    etag = models.CharField(max_length=200, blank=True)
    version_sincronizada = models.PositiveIntegerField(default=0)
    cancelado = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["calendario_id", "evento_id"], name="google_evento_unico")]


class TrabajoSincronizacion(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        PROCESANDO = "procesando", "Procesando"
        HECHO = "hecho", "Hecho"
        ERROR = "error", "Error"
        CONFLICTO = "conflicto", "Conflicto externo"
        OBSOLETO = "obsoleto", "Obsoleto"

    cita = models.ForeignKey("agenda.Cita", on_delete=models.PROTECT)
    conexion = models.ForeignKey(ConexionGoogle, on_delete=models.PROTECT)
    version = models.PositiveIntegerField()
    estado = models.CharField(max_length=16, choices=Estado.choices, default=Estado.PENDIENTE)
    intentos = models.PositiveIntegerField(default=0)
    proximo_intento = models.DateTimeField()
    bloqueo_hasta = models.DateTimeField(null=True, blank=True)
    token_bloqueo = models.UUIDField(null=True, blank=True)
    error = models.CharField(max_length=240, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["cita", "conexion", "version"], name="google_trabajo_unico")]
        indexes = [models.Index(fields=["estado", "proximo_intento"], name="google_pendientes")]
