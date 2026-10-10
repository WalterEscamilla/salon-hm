from decimal import Decimal

from django import template

from apps.inventario.constants import STOCK_QUANTUM
from apps.inventario.messages import Info

register = template.Library()


@register.filter
def cantidad(valor):
    """Hasta tres decimales, sin ceros sobrantes; indica las equivalencias aproximadas."""
    if valor is None:
        return ""
    numero = Decimal(valor)
    mostrado = numero.quantize(STOCK_QUANTUM)
    texto = format(mostrado, "f").rstrip("0").rstrip(".")
    return texto if numero == mostrado else f"{Info.Approximation} {texto}"
