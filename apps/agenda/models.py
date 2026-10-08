import uuid

from django.conf import settings
from django.db import models


class Cita(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        CONFIRMADA = "confirmada", "Confirmada"
        COMPLETADA = "completada", "Completada"
        CANCELADA = "cancelada", "Cancelada"
        NO_ASISTIO = "no_asistio", "No asistió"

    class Sincronizacion(models.TextChoices):
        SIN_CONEXION = "sin_conexion", "Sin conexión a Google"
        PENDIENTE = "pendiente", "Pendiente de sincronizar"
        SINCRONIZADA = "sincronizada", "Sincronizada"
        ERROR = "error", "Error de sincronización"
        CONFLICTO = "conflicto", "Cambio externo en Google"

    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.PROTECT)
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.CharField("Servicio previsto", max_length=240, blank=True)
    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    notas = models.TextField(blank=True, max_length=3000)
    estado = models.CharField(max_length=16, choices=Estado.choices, default=Estado.PENDIENTE)
    version = models.PositiveIntegerField(default=1)
    clave_operacion = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    hash_operacion = models.CharField(max_length=64, editable=False)
    sincronizacion = models.CharField(max_length=16, choices=Sincronizacion.choices, default=Sincronizacion.SIN_CONEXION)
    error_sincronizacion = models.CharField(max_length=240, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["inicio", "pk"]
        constraints = [models.CheckConstraint(condition=models.Q(fin__gt=models.F("inicio")), name="cita_fin_despues_inicio")]
        indexes = [models.Index(fields=["estado", "inicio"], name="cita_estado_inicio"), models.Index(fields=["responsable", "inicio"], name="cita_responsable_inicio")]


class ServicioPrevisto(models.Model):
    cita = models.ForeignKey(Cita, on_delete=models.CASCADE, related_name="servicios_previstos")
    servicio = models.ForeignKey("catalogos.Servicio", on_delete=models.PROTECT)
    nombre = models.CharField(max_length=120)
    duracion_minutos = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["cita", "servicio"], name="cita_servicio_unico")]


class RegistroServicioAgenda(models.Model):
    """Una atención por cita o por ocurrencia del calendario de Google."""
    atencion = models.OneToOneField("atenciones.Atencion", on_delete=models.PROTECT, related_name="registro_agenda")
    cita = models.OneToOneField(Cita, null=True, blank=True, on_delete=models.PROTECT, related_name="registro_servicio")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    calendario_id = models.CharField(max_length=320, blank=True)
    evento_id = models.CharField(max_length=1024, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["usuario", "calendario_id", "evento_id"], condition=~models.Q(evento_id=""), name="servicio_evento_google_unico"),
            models.CheckConstraint(condition=models.Q(cita__isnull=False) | (~models.Q(calendario_id="") & ~models.Q(evento_id="")), name="servicio_agenda_tiene_origen"),
        ]
