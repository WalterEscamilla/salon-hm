from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import AccesoView, entrar_google

app_name = "cuentas"
urlpatterns = [
    path("entrar/", AccesoView.as_view(), name="login"),
    path("google/entrar/", entrar_google, name="google_login"),
    path("salir/", LogoutView.as_view(), name="logout"),
]
