"""Reglas y códigos estables del inventario."""
from decimal import Decimal

from django.db import models

from .messages import Label

ZERO = Decimal("0")
STOCK_MAX_DIGITS = 14
STOCK_DECIMAL_PLACES = 3
STOCK_QUANTUM = Decimal("0.001")
MAX_STOCK = Decimal(10) ** (STOCK_MAX_DIGITS - STOCK_DECIMAL_PLACES) - STOCK_QUANTUM
FINGERPRINT_LENGTH = 64
INITIAL_FIELDS = ("cantidad_inicial", "modo_cantidad", "clave_alta")
PRODUCT_SAVED = "producto.guardado"
PRODUCT_CREATED_WITH_STOCK = "producto.conteo_inicial"
PRODUCT_ENTITY = "inventario.Producto"


class QuantityMode(models.TextChoices):
    BASE = "base", Label.BaseQuantity
    ENVASES = "envases", Label.ContainersQuantity
