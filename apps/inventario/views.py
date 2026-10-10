from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .forms import MovimientoForm, ProductoForm, ProductoPresentacionForm
from .models import Producto
from .messages import Info, Label
from .services import guardar_producto, registrar_movimiento


@permission_required("inventario.view_producto", raise_exception=True)
@never_cache
def listado(request):
    productos = Producto.objects.all()
    busqueda = request.GET.get("q", "").strip()[:160]
    if busqueda:
        from django.db.models import Q
        productos = productos.filter(Q(nombre__icontains=busqueda) | Q(marca__icontains=busqueda) | Q(descripcion__icontains=busqueda))
    return render(request, "inventario/listado.html", {"productos": Paginator(productos, 30).get_page(request.GET.get("page")), "busqueda": busqueda, "labels": Label, "info": Info})


@permission_required("inventario.view_producto", raise_exception=True)
@never_cache
def detalle(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    movimientos = producto.movimientos.all() if request.user.has_perm("inventario.view_movimientostock") else producto.movimientos.none()
    return render(request, "inventario/detalle.html", {"producto": producto, "movimientos": Paginator(movimientos.select_related("actor"), 30).get_page(request.GET.get("page")), "info": Info, "labels": Label})


@require_http_methods(["GET", "POST"])
@never_cache
def editar(request, pk=None):
    if not request.user.has_perm("inventario.change_producto" if pk else "inventario.add_producto"):
        raise PermissionDenied
    producto = get_object_or_404(Producto, pk=pk) if pk else None
    tipo_form = ProductoPresentacionForm if producto is None or producto.presentacion else ProductoForm
    form = tipo_form(request.POST if request.method == "POST" else None, instance=producto)
    if request.method == "POST" and form.is_valid():
        try:
            producto = guardar_producto(actor=request.user, datos=form.cleaned_data, producto_id=pk)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, Info.ProductSaved if pk else Info.SavedWithStock if form.cleaned_data.get("stock_inicial_calculado") is not None else Info.PendingCount)
            return redirect("inventario:detalle", pk=producto.pk)
    return render(request, "inventario/formulario.html", {"form": form, "titulo": Label.EditProduct if pk else Label.NewProduct, "labels": Label, "info": Info,
        "por_presentacion": isinstance(form, ProductoPresentacionForm)})


@permission_required("inventario.add_movimientostock", raise_exception=True)
@require_http_methods(["GET", "POST"])
@never_cache
def movimiento(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    form = MovimientoForm(request.POST if request.method == "POST" else None, initial={"unidad": producto.unidad, "version": producto.version})
    if request.method == "POST" and form.is_valid():
        try:
            registrar_movimiento(actor=request.user, producto_id=pk, datos=form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Guardamos el movimiento y actualizamos el stock.")
            return redirect("inventario:detalle", pk=pk)
    return render(request, "formulario.html", {"form": form, "titulo": f"Stock · {producto.nombre}", "descripcion": f"Existencias actuales: {producto.existencias} {producto.unidad}. Para ajuste escribe el conteo final; para entrada o salida escribe la cantidad a agregar o descontar.", "volver": "inventario:listado"})
