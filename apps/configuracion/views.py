from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .forms import ConfiguracionForm
from .queries import obtener_configuracion
from .services import actualizar_configuracion


@permission_required("configuracion.change_configuracionsalon", raise_exception=True)
@require_http_methods(["GET", "POST"])
@never_cache
def editar(request):
    salon = obtener_configuracion()
    form = ConfiguracionForm(request.POST if request.method == "POST" else None, instance=salon)
    if request.method == "POST" and form.is_valid():
        actualizar_configuracion(actor=request.user, **form.cleaned_data)
        messages.success(request, "Guardamos la configuración del salón.")
        return redirect("configuracion:editar")
    return render(request, "configuracion/editar.html", {"form": form})
