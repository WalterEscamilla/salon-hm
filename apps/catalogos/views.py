from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .forms import ServicioForm
from .models import Servicio
from .services import guardar_servicio


@permission_required("catalogos.view_servicio", raise_exception=True)
@never_cache
def listado(request):
    return render(request, "catalogos/listado.html", {"servicios": Servicio.objects.all()})


@require_http_methods(["GET", "POST"])
@never_cache
def editar(request, pk=None):
    permiso = "catalogos.change_servicio" if pk else "catalogos.add_servicio"
    if not request.user.has_perm(permiso):
        raise PermissionDenied
    servicio = get_object_or_404(Servicio, pk=pk) if pk else None
    form = ServicioForm(request.POST if request.method == "POST" else None, instance=servicio)
    if request.method == "POST" and form.is_valid():
        guardar_servicio(actor=request.user, datos=form.cleaned_data, servicio_id=pk)
        messages.success(request, "Guardamos el servicio.")
        return redirect("catalogos:listado")
    return render(request, "formulario.html", {"form": form, "titulo": "Editar servicio" if pk else "Nuevo servicio", "descripcion": "Solo el nombre es obligatorio. Precio y duración pueden quedar vacíos; el precio de cada visita se guarda en su historial.", "volver": "catalogos:listado"})
