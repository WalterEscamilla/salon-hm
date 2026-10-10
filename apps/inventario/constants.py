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
PRESENTATION_MAX_LENGTH = 80
UNIT_MAX_LENGTH = 24
OPTION_KEY_LENGTH = PRESENTATION_MAX_LENGTH * 3
OPTION_SAVED = "opcion_inventario.guardada"
OPTION_ENTITY = "inventario.OpcionInventario"
DEFAULT_PRESENTATIONS = ("Botellas", "Tubos")
DEFAULT_CONTENT_UNITS = ("ml", "l", "g", "unidad")
PRESENTATION_FIELDS = ("nombre", "presentacion", "contenido_envase", "unidad", "corregir_presentacion", "cantidad_inicial", "costo_envase", "minimo_presentaciones")
NEW_OPTION = "__nueva__"
NEW_OPTION_SUFFIX = "_nueva"
QUANTITY_INPUT_MAX_LENGTH = 40
INVALID_QUANTITY_INPUT = "invalid"
FRACTION_PATTERN = r"^\d+/[1-9]\d*$"
FRACTION_CHOICES = (("", Label.NoFraction), ("1/4", Label.Quarter),
    ("1/3", Label.Third), ("1/2", Label.Half), ("2/3", Label.TwoThirds), ("3/4", Label.ThreeQuarters))
PRODUCT_PRESENTATION_CORRECTED = "producto.presentacion_corregida"


class OptionType(models.TextChoices):
    PRESENTATION = "presentacion", Label.Presentation
    UNIT = "unidad", Label.Unit


class QuantityMode(models.TextChoices):
    BASE = "base", Label.BaseQuantity
    ENVASES = "envases", Label.ContainersQuantity
