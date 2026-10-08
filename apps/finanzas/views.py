from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.atenciones.models import Atencion
from .forms import AnularGastoForm, BaseFinancieraForm, GastoForm
from .models import BaseFinanciera, Gasto
from .queries import resumen_financiero
from .services import anular_gasto, guardar_base, guardar_gasto


@permission_required(["finanzas.view_basefinanciera", "finanzas.view_gasto", "atenciones.view_atencion"], raise_exception=True)
@require_http_methods(["GET"])
@never_cache
def inicio(request):
    resumen = resumen_financiero()
    desde = resumen["base"].fecha_inicio
    gastos = Gasto.objects.filter(fecha__gte=desde, fecha__lte=resumen["hasta"])
    historial = request.GET.get("historial") == "1"
    if historial:
        gastos = Gasto.objects.all()
    visitas = Atencion.objects.select_related("cliente").filter(fecha__gte=desde, fecha__lte=resumen["hasta"])
    return render(request, "finanzas/inicio.html", {"resumen": resumen, "gastos": Paginator(gastos, 20).get_page(request.GET.get("page")), "visitas": visitas[:20] if request.user.has_perm("clientes.view_cliente") else [], "historial": historial, "gastos_anteriores": Gasto.objects.filter(fecha__lt=desde).count()})


@require_http_methods(["GET", "POST"])
@never_cache
def editar_gasto(request, pk=None):
    if not request.user.has_perm("finanzas.change_gasto" if pk else "finanzas.add_gasto"):
        raise PermissionDenied
    gasto = get_object_or_404(Gasto, pk=pk) if pk else None
    if gasto and gasto.anulado_en:
        messages.warning(request, "Este gasto ya fue anulado. Puedes registrar otro pago.")
        return redirect("finanzas:inicio")
    inicial = {campo: getattr(gasto, campo) for campo in GastoForm.base_fields} if gasto else {}
    form = GastoForm(request.POST if request.method == "POST" else None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        try:
            guardado = guardar_gasto(actor=request.user, datos=form.cleaned_data, gasto_id=pk)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Gasto guardado.")
            if guardado.fecha < BaseFinanciera.objects.get(pk=1).fecha_inicio:
                messages.warning(request, "Este pago es anterior al inicio del control; se conserva en el historial y no cambia el saldo actual.")
            return redirect("finanzas:inicio")
    return render(request, "formulario.html", {"form": form, "titulo": "Corregir gasto" if gasto else "Registrar gasto", "descripcion": "Registra un pago realizado. Para la luz semanal, agrega cada pago de $200 cuando se haga. No repitas gastos que ya descontaste en una visita.", "volver": "finanzas:inicio"})


@permission_required("finanzas.change_gasto", raise_exception=True)
@require_http_methods(["GET", "POST"])
@never_cache
def anular(request, pk):
    gasto = get_object_or_404(Gasto, pk=pk)
    form = AnularGastoForm(request.POST if request.method == "POST" else None, initial={"version": gasto.version})
    if request.method == "POST" and form.is_valid():
        try:
            anular_gasto(actor=request.user, gasto_id=pk, datos=form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Gasto anulado. Se conserva el registro y deja de descontarse del saldo.")
            return redirect("finanzas:inicio")
    return render(request, "finanzas/anular.html", {"form": form, "gasto": gasto})


@permission_required("finanzas.change_basefinanciera", raise_exception=True)
@require_http_methods(["GET", "POST"])
@never_cache
def editar_base(request):
    base = BaseFinanciera.objects.get(pk=1)
    form = BaseFinancieraForm(request.POST if request.method == "POST" else None, initial={campo: getattr(base, campo) for campo in BaseFinancieraForm.base_fields})
    if request.method == "POST" and form.is_valid():
        try:
            guardar_base(actor=request.user, datos=form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Saldo inicial y fecha de inicio actualizados.")
            return redirect("finanzas:inicio")
    return render(request, "formulario.html", {"form": form, "titulo": "Saldo inicial", "descripcion": "Esta base representa el dinero disponible antes de los movimientos del período. Al cambiarla se recalcula el saldo; tus visitas y gastos se conservan.", "volver": "finanzas:inicio"})
