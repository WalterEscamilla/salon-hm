from django.urls import path

from . import views

app_name = "clientes"
urlpatterns = [path("", views.listado, name="listado"), path("nueva/", views.nuevo, name="nueva"), path("<int:pk>/", views.detalle, name="detalle"), path("<int:pk>/editar/", views.editar, name="editar")]
