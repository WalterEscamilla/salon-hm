from django.urls import path
from . import views

app_name = "asistente"
urlpatterns = [path("", views.chat, name="chat"), path("borradores/<uuid:pk>/", views.borrador, name="borrador")]
