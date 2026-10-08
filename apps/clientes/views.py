import re

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .forms import ClienteForm
from .models import Cliente
from .services import guardar_cliente


@permission_required("clientes.view_cliente", raise_exception=True)
@never_cache
def listado(request):
    consulta = request.GET.get("q", "").strip()[:160]
    clientes = Cliente.objects.filter(archivado_en__isnull=True)
    if consulta:
        filtro = Q(nombre__icontains=consulta)
        digitos = re.sub(r"\D", "", consulta)
        if digitos:
            filtro |= Q(telefono_normalizado__contains=digitos)
        clientes = clientes.filter(filtro)
    return render(request, "clientes/listado.html", {"pagina": Paginator(clientes, 30).get_page(request.GET.get("pagina")), "consulta": consulta})


@permission_required("clientes.view_cliente", raise_exception=True)
@never_cache
def detalle(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    atenciones = cliente.atenciones.all() if request.user.has_perm("atenciones.view_atencion") else cliente.atenciones.none()
    return render(request, "clientes/detalle.html", {"cliente": cliente, "ultima": atenciones.first(), "historial": Paginator(atenciones, 30).get_page(request.GET.get("page"))})


@permission_required("clientes.add_cliente", raise_exception=True)
@require_http_methods(["GET", "POST"])
@never_cache
def nuevo(request):
    form = ClienteForm(request.POST if request.method == "POST" else None)
    volver_agenda = request.GET.get("volver") == "agenda"
    if request.method == "POST" and form.is_valid():
        cliente = guardar_cliente(actor=request.user, datos=form.cleaned_data)
        messages.success(request, "La clienta quedó registrada.")
        if volver_agenda:
            from django.urls import reverse
            return redirect(f"{reverse('agenda:nueva')}?cliente={cliente.pk}")
        return redirect("clientes:listado")
    return render(request, "formulario.html", {"form": form, "titulo": "Nueva clienta", "descripcion": "Solo el nombre es obligatorio. Si hay nombres iguales, el teléfono te ayudará a distinguirlos.", "volver": "clientes:listado"})


@permission_required("clientes.change_cliente", raise_exception=True)
@require_http_methods(["GET", "POST"])
@never_cache
def editar(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    form = ClienteForm(request.POST if request.method == "POST" else None, instance=cliente)
    if request.method == "POST" and form.is_valid():
        guardar_cliente(actor=request.user, datos=form.cleaned_data, cliente_id=pk)
        messages.success(request, "Guardamos los datos de la clienta.")
        return redirect("clientes:listado")
    return render(request, "formulario.html", {"form": form, "titulo": "Editar clienta", "volver": "clientes:listado"})
