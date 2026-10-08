from django.urls import path

from . import views

app_name = "agenda"
urlpatterns = [path("", views.listado, name="listado"), path("nueva/", views.editar, name="nueva"), path("<int:pk>/", views.detalle, name="detalle"), path("<int:pk>/editar/", views.editar, name="editar"), path("<int:pk>/sincronizar/", views.sincronizar, name="sincronizar")]

