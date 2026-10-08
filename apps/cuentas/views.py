from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from . import google
from .forms import AccesoForm


class AccesoView(LoginView):
    template_name = "cuentas/login.html"
    authentication_form = AccesoForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        self.request.session.pop("google_login", None)
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["google_login_configurado"] = google.configurado()
        return context


@login_not_required
@require_POST
@never_cache
def entrar_google(request):
    if request.user.is_authenticated:
        return redirect("core:inicio")
    try:
        return redirect(google.iniciar(request))
    except Exception:
        messages.error(request, "No se pudo iniciar el acceso con Google. Puedes entrar con tu usuario y contraseña.")
        return redirect("cuentas:login")


def retorno_google(request):
    if request.user.is_authenticated:
        request.session.pop("google_login", None)
        response = redirect("core:inicio")
        response["Referrer-Policy"] = "no-referrer"
        return response
    try:
        usuario = google.completar(request)
        login(request, usuario, backend="django.contrib.auth.backends.ModelBackend")
        response = redirect("core:inicio")
    except Exception:
        messages.error(request, "No se pudo verificar el acceso. Selecciona la cuenta de Google autorizada para este salón e intenta de nuevo.")
        response = redirect("cuentas:login")
    response["Referrer-Policy"] = "no-referrer"
    return response
