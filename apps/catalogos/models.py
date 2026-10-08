from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Servicio(models.Model):
    nombre = models.CharField(max_length=120)
    descripcion = models.TextField("Descripción", blank=True, max_length=2000)
    duracion_minutos = models.PositiveIntegerField("Duración de referencia (opcional)", null=True, blank=True, validators=[MinValueValidator(1)], help_text="Déjala vacía si depende de cada visita.")
    precio_base = models.DecimalField("Precio de referencia (MXN, opcional)", max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))], help_text="Déjalo vacío si depende de cada clienta. El precio real se registra en la visita.")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre", "pk"]
        constraints = [models.CheckConstraint(condition=models.Q(precio_base__isnull=True) | models.Q(precio_base__gte=0), name="servicio_precio_no_negativo"), models.CheckConstraint(condition=models.Q(duracion_minutos__isnull=True) | models.Q(duracion_minutos__gt=0), name="servicio_duracion_positiva")]

    def __str__(self):
        return self.nombre
