from django.urls import path
from . import views

app_name = "finanzas"
urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("base/", views.editar_base, name="base"),
    path("gastos/nuevo/", views.editar_gasto, name="nuevo_gasto"),
    path("gastos/<int:pk>/editar/", views.editar_gasto, name="editar_gasto"),
    path("gastos/<int:pk>/anular/", views.anular, name="anular_gasto"),
]
