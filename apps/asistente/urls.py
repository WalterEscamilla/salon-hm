from django.urls import path
from . import views

app_name = "asistente"
urlpatterns = [
    path("", views.chat, name="chat"),
    path("borradores/<uuid:pk>/", views.borrador, name="borrador"),
    path("<path:ruta>", views.propuesta_no_disponible, name="propuesta_no_disponible"),
]
