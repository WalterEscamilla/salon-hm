from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import models


def validar_zona_horaria(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError("Escribe una zona válida, por ejemplo America/Merida.")


class ConfiguracionSalon(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    nombre = models.CharField("Nombre del salón", max_length=100, default="Salón HM")
    moneda = models.CharField(max_length=3, default="MXN", editable=False)
    zona_horaria = models.CharField("Zona horaria", max_length=64, default="America/Merida", validators=[validar_zona_horaria])
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuración del salón"
        verbose_name_plural = "configuración del salón"
        constraints = [
            models.CheckConstraint(condition=models.Q(pk=1), name="salon_unica_configuracion"),
            models.CheckConstraint(condition=models.Q(moneda="MXN"), name="salon_moneda_mxn"),
        ]

    def __str__(self):
        return self.nombre

