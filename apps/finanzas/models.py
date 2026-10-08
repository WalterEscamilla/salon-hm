from decimal import Decimal
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class BaseFinanciera(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    saldo_inicial = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("10000.00"), validators=[MinValueValidator(Decimal("0"))])
    fecha_inicio = models.DateField(default=timezone.localdate)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(pk=1), name="finanzas_base_unica"),
            models.CheckConstraint(condition=models.Q(saldo_inicial__gte=0), name="finanzas_base_no_negativa"),
        ]


class Gasto(models.Model):
    class Categoria(models.TextChoices):
        LUZ = "luz", "Luz"
        MATERIALES = "materiales", "Compra de productos o materiales"
        EQUIPO = "equipo", "Equipo y mobiliario"
        RENTA = "renta", "Renta"
        OTROS = "otros", "Otros gastos"

    fecha = models.DateField()
    concepto = models.CharField(max_length=200)
    categoria = models.CharField(max_length=20, choices=Categoria.choices, default=Categoria.OTROS)
    importe = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    notas = models.TextField(max_length=2000, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    clave_operacion = models.UUIDField(default=uuid.uuid4, unique=True)
    huella_operacion = models.CharField(max_length=64)
    version = models.PositiveIntegerField(default=1)
    creado_en = models.DateTimeField(auto_now_add=True)
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-fecha", "-creado_en", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(importe__gt=0), name="finanzas_gasto_positivo"),
            models.CheckConstraint(condition=(models.Q(anulado_en__isnull=True, motivo_anulacion="") | (models.Q(anulado_en__isnull=False) & ~models.Q(motivo_anulacion=""))), name="finanzas_anulacion_con_motivo"),
        ]

    def __str__(self):
        return self.concepto
