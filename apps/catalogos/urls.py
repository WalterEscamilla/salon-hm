from django.urls import path

from . import views

app_name = "catalogos"
urlpatterns = [path("", views.listado, name="listado"), path("nuevo/", views.editar, name="nuevo"), path("<int:pk>/editar/", views.editar, name="editar")]

