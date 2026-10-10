"""Selectores para catálogos ampliables y fracciones de presentaciones."""
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from django import forms

from .constants import FRACTION_CHOICES, INVALID_QUANTITY_INPUT, NEW_OPTION, NEW_OPTION_SUFFIX, QUANTITY_INPUT_MAX_LENGTH
from .messages import Label


class OpcionAmpliableWidget(forms.Select):
    template_name = "inventario/widgets/opcion.html"

    def value_from_datadict(self, data, files, name):
        valor = super().value_from_datadict(data, files, name)
        return data.get(name + NEW_OPTION_SUFFIX, "") if valor == NEW_OPTION else valor

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"].update({"new_value": NEW_OPTION,
            "new_name": name + NEW_OPTION_SUFFIX, "new_label": Label.NewOptionName,
            "max_length": context["widget"]["attrs"].pop("data_maxlength")})
        return context


class FraccionPresentacionWidget(forms.MultiWidget):
    template_name = "inventario/widgets/fraccion.html"

    def __init__(self, attrs=None):
        super().__init__([forms.NumberInput(attrs={"min": "0", "step": "any"}),
            forms.Select(choices=FRACTION_CHOICES)], attrs)

    def decompress(self, value):
        if value in (None, ""):
            return [None, ""]
        try:
            numero = Fraction(str(value))
            enteros, resto = divmod(numero.numerator, numero.denominator)
            fraccion = str(Fraction(resto, numero.denominator)) if resto else ""
            if fraccion in dict(FRACTION_CHOICES):
                return [enteros, fraccion]
        except (ValueError, ZeroDivisionError):
            pass
        return [value, ""]

    def id_for_label(self, id_):
        return f"{id_}_0" if id_ else ""

    def value_from_datadict(self, data, files, name):
        # Compatibilidad con formularios antiguos, servicios y borradores JSON.
        if name in data:
            return data.get(name)
        completo, fraccion = super().value_from_datadict(data, files, name)
        if not fraccion:
            return completo
        if fraccion not in dict(FRACTION_CHOICES) or len(str(completo or "")) > QUANTITY_INPUT_MAX_LENGTH:
            return INVALID_QUANTITY_INPUT
        try:
            base = Decimal(completo or "0")
            if not base.is_finite() or base < 0:
                return INVALID_QUANTITY_INPUT
            return str(Fraction(base) + Fraction(fraccion))
        except (InvalidOperation, ValueError, ZeroDivisionError):
            return INVALID_QUANTITY_INPUT

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["labels"] = (Label.FullPresentations, Label.OpenPresentation)
        context["widget"]["subwidgets"][1]["attrs"]["class"] = "form-select"
        return context
