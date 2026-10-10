import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from .constants import FINGERPRINT_LENGTH


class Producto(models.Model):
    class Unidad(models.TextChoices):
        GRAMOS = "g", "Gramos (g)"
        MILILITROS = "ml", "Mililitros (ml)"
        UNIDADES = "unidad", "Unidades"

    nombre = models.CharField(max_length=160)
    marca = models.CharField(max_length=100, blank=True)
    descripcion = models.TextField("Descripción / tono", max_length=2000, blank=True)
    unidad = models.CharField(max_length=10, choices=Unidad.choices)
    contenido_envase = models.DecimalField("Contenido por envase (en la unidad elegida)", max_digits=12, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(Decimal("0.001"))])
    costo_envase = models.DecimalField("Costo por envase (MXN, si lo conoces)", max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))])
    stock_minimo = models.DecimalField("Avisar cuando queden", max_digits=14, decimal_places=3, default=0, validators=[MinValueValidator(Decimal("0"))])
    existencias = models.DecimalField(max_digits=14, decimal_places=3, default=0, editable=False)
    version = models.PositiveIntegerField(default=1, editable=False)
    activo = models.BooleanField(default=True)
    clave_alta = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    huella_alta = models.CharField(max_length=FINGERPRINT_LENGTH, blank=True, editable=False)

    class Meta:
        ordering = ["nombre", "marca", "pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(existencias__gte=0), name="producto_stock_no_negativo"),
            models.CheckConstraint(condition=models.Q(stock_minimo__gte=0), name="producto_minimo_no_negativo"),
            models.CheckConstraint(condition=models.Q(contenido_envase__isnull=True) | models.Q(contenido_envase__gt=0), name="producto_contenido_positivo"),
            models.CheckConstraint(condition=models.Q(costo_envase__isnull=True) | models.Q(costo_envase__gte=0), name="producto_costo_no_negativo"),
        ]

    @property
    def costo_por_unidad(self):
        if self.contenido_envase is not None and self.costo_envase is not None:
            return self.costo_envase / self.contenido_envase
        return None

    @property
    def stock_bajo(self):
        return self.existencias <= self.stock_minimo

    @property
    def envases_equivalentes(self):
        if self.contenido_envase is not None and self.contenido_envase > 0:
            return self.existencias / self.contenido_envase
        return None

    def __str__(self):
        return f"{self.nombre} · {self.marca or 'Sin marca'} · ID {self.pk} · {self.unidad}"


class MovimientoStock(models.Model):
    class Tipo(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        SALIDA = "salida", "Salida / consumo"
        AJUSTE = "ajuste", "Ajuste al conteo real"

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="movimientos")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    unidad = models.CharField(max_length=10, choices=Producto.Unidad.choices)
    saldo_anterior = models.DecimalField(max_digits=14, decimal_places=3)
    saldo_nuevo = models.DecimalField(max_digits=14, decimal_places=3)
    costo_por_unidad = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    motivo = models.CharField(max_length=300)
    origen = models.CharField(max_length=16, choices=[("formulario", "Formulario"), ("asistente", "Asistente")])
    fecha = models.DateTimeField(auto_now_add=True)
    clave_operacion = models.UUIDField(default=uuid.uuid4, unique=True)
    huella = models.CharField(max_length=64)

    class Meta:
        ordering = ["-fecha", "-pk"]
        constraints = [models.CheckConstraint(condition=models.Q(saldo_nuevo__gte=0), name="movimiento_saldo_no_negativo")]
