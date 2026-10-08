from django.urls import path

from . import views

app_name = "integraciones"
urlpatterns = [
    path("", views.configuracion, name="calendario"),
    path("google/conectar/", views.conectar, name="conectar"),
    path("google/retorno/", views.retorno, name="retorno"),
    path("google/elegir/", views.elegir, name="elegir"),
    path("google/desconectar/", views.desconectar, name="desconectar"),
    path("google/conflicto/<int:pk>/", views.resolver, name="resolver"),
]
