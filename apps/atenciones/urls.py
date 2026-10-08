from django.urls import path
from . import views

app_name = "atenciones"
urlpatterns = [path("", views.listado, name="listado"), path("nuevo/", views.editar, name="nueva"), path("<int:pk>/", views.detalle, name="detalle"), path("<int:pk>/editar/", views.editar, name="editar")]
