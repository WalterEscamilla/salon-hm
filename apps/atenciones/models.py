from decimal import Decimal
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Atencion(models.Model):
    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.PROTECT, related_name="atenciones")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateField("Fecha del servicio")
    servicio = models.TextField("Servicio realizado", max_length=2000)
    precio_cobrado = models.DecimalField("Precio cobrado por esta visita (MXN)", max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))])
    materiales = models.TextField("Materiales, tonos o fórmula utilizados", max_length=4000, blank=True)
    notas = models.TextField("Notas para la próxima visita", max_length=2000, blank=True)
    version = models.PositiveIntegerField(default=1)
    clave_operacion = models.UUIDField(default=uuid.uuid4, unique=True)
    huella_operacion = models.CharField(max_length=64)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha", "-creado_en", "-pk"]
        constraints = [models.CheckConstraint(condition=models.Q(precio_cobrado__isnull=True) | models.Q(precio_cobrado__gte=0), name="atencion_precio_no_negativo")]

    def __str__(self):
        return f"{self.cliente.nombre} · {self.fecha}"
