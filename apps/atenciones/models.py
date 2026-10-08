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
    costo_materiales = models.DecimalField("Costo de materiales utilizados (MXN)", max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))])
    otros_gastos = models.DecimalField("Otros gastos de esta visita (MXN)", max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))])
    gastos_pagados_en_visita = models.BooleanField(default=False)
    materiales = models.TextField("Materiales, tonos o fórmula utilizados", max_length=4000, blank=True)
    notas = models.TextField("Notas para la próxima visita", max_length=2000, blank=True)
    version = models.PositiveIntegerField(default=1)
    clave_operacion = models.UUIDField(default=uuid.uuid4, unique=True)
    huella_operacion = models.CharField(max_length=64)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha", "-creado_en", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(precio_cobrado__isnull=True) | models.Q(precio_cobrado__gte=0), name="atencion_precio_no_negativo"),
            models.CheckConstraint(condition=models.Q(costo_materiales__isnull=True) | models.Q(costo_materiales__gte=0), name="atencion_materiales_no_negativos"),
            models.CheckConstraint(condition=models.Q(otros_gastos__isnull=True) | models.Q(otros_gastos__gte=0), name="atencion_otros_no_negativos"),
            models.CheckConstraint(condition=models.Q(gastos_pagados_en_visita=False) | models.Q(costo_materiales__isnull=False, otros_gastos__isnull=False), name="atencion_pago_costos_conocidos"),
        ]

    @property
    def costo_total(self):
        if self.costo_materiales is None or self.otros_gastos is None:
            return None
        return self.costo_materiales + self.otros_gastos

    @property
    def margen(self):
        if self.precio_cobrado is None or self.costo_total is None:
            return None
        return self.precio_cobrado - self.costo_total

    def __str__(self):
        return f"{self.cliente.nombre} · {self.fecha}"
