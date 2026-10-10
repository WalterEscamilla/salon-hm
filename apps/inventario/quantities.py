"""Conversión exacta de fracciones de una presentación a su contenido."""
import re
from decimal import Decimal
from fractions import Fraction

from django import forms
from django.core.exceptions import ValidationError

from .constants import (FRACTION_PATTERN, MAX_STOCK, QUANTITY_INPUT_MAX_LENGTH,
    STOCK_DECIMAL_PLACES, STOCK_MAX_DIGITS, STOCK_QUANTUM, ZERO)
from .messages import Error


class CantidadPresentacionesField(forms.Field):
    """Conserva tercios como racionales, incluso al serializar un borrador."""
    widget = forms.NumberInput(attrs={"min": str(ZERO), "step": str(STOCK_QUANTUM)})
    default_error_messages = {"invalid": Error.InvalidQuantity}

    def to_python(self, value):
        if value in self.empty_values:
            return None
        texto = str(value).strip()
        if len(texto) > QUANTITY_INPUT_MAX_LENGTH:
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        if re.fullmatch(FRACTION_PATTERN, texto):
            cantidad = Fraction(texto)
            if cantidad > Fraction(MAX_STOCK):
                raise ValidationError(Error.StockTooLarge)
            return str(cantidad) if cantidad.denominator != 1 else Decimal(cantidad.numerator)
        return forms.DecimalField(max_digits=STOCK_MAX_DIGITS,
            decimal_places=STOCK_DECIMAL_PLACES, min_value=ZERO,
            error_messages={"invalid": Error.InvalidQuantity}).clean(value)


def contenido_exacto(cantidad, contenido):
    """Rechaza cantidades fuera de rango o que requerirían redondear stock."""
    total = Fraction(cantidad) * Fraction(contenido)
    if total < 0 or total > Fraction(MAX_STOCK):
        raise ValidationError(Error.StockTooLarge)
    escala = 10 ** STOCK_DECIMAL_PLACES
    numerador = total.numerator * escala
    if numerador % total.denominator:
        raise ValidationError(Error.StockPrecision)
    return (Decimal(numerador // total.denominator) / escala).quantize(STOCK_QUANTUM)
