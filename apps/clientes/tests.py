from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .services import guardar_cliente


class ClienteTests(TestCase):
    def test_busqueda_parcial_telefono_y_sin_resultados(self):
        actor = get_user_model().objects.create_superuser(username="admin", password="Pruebas123!")
        guardar_cliente(actor=actor, datos={"nombre": "María López", "telefono": "999 123 4567", "notas": ""})
        self.client.force_login(actor)
        self.assertContains(self.client.get(reverse("clientes:listado"), {"q": "López"}), "María López")
        self.assertContains(self.client.get(reverse("clientes:listado"), {"q": "1234567"}), "María López")
        self.assertContains(self.client.get(reverse("clientes:listado"), {"q": "Sin coincidencias"}), "No encontramos clientas")

