from decimal import Decimal

from django.db import transaction
from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.atenciones.models import Atencion
from apps.configuracion.models import ConfiguracionSalon
from .models import BaseFinanciera, Gasto


def sumar(campo, **kwargs):
    return Coalesce(Sum(campo, **kwargs), Value(Decimal("0.00")), output_field=DecimalField(max_digits=20, decimal_places=2))


@transaction.atomic
def resumen_financiero():
    # La misma cerradura que usan los pagos y visitas evita mezclar estados al sumar.
    ConfiguracionSalon.objects.select_for_update().get(pk=1)
    base = BaseFinanciera.objects.get(pk=1)
    visitas = Atencion.objects.filter(fecha__gte=base.fecha_inicio, fecha__lte=timezone.localdate())
    completos = Q(precio_cobrado__isnull=False, costo_materiales__isnull=False, otros_gastos__isnull=False)
    totales = visitas.aggregate(
        ingresos=sumar("precio_cobrado"),
        pagos_visitas=sumar(F("costo_materiales") + F("otros_gastos"), filter=Q(gastos_pagados_en_visita=True)),
        margen=sumar(F("precio_cobrado") - F("costo_materiales") - F("otros_gastos"), filter=completos),
        visitas=Count("pk"), visitas_completas=Count("pk", filter=completos),
        precios_pendientes=Count("pk", filter=Q(precio_cobrado__isnull=True)),
    )
    gastos = Gasto.objects.filter(fecha__gte=base.fecha_inicio, fecha__lte=timezone.localdate(), anulado_en__isnull=True).aggregate(total=sumar("importe"))["total"]
    return {"base": base, **totales, "gastos": gastos, "saldo": base.saldo_inicial + totales["ingresos"] - gastos - totales["pagos_visitas"], "visitas_pendientes": totales["visitas"] - totales["visitas_completas"], "hasta": timezone.localdate()}
