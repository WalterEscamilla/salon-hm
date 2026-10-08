from datetime import datetime, timezone as datetime_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.test import Client, TestCase
from django.urls import reverse

from apps.configuracion.services import actualizar_configuracion


class AccesoPrivadoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(
            username="administradora", email="prueba@example.invalid", password="UnaClaveSoloParaPruebas123!"
        )

    def test_paginas_privadas_exigen_login(self):
        for url in [reverse("core:inicio"), reverse("configuracion:editar"), "/admin/"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("next=", response.url)

    def test_login_redirige_a_inicio_y_logout_es_post(self):
        response = self.client.post(reverse("cuentas:login"), {"username": "administradora", "password": "UnaClaveSoloParaPruebas123!"})
        self.assertRedirects(response, reverse("core:inicio"))
        self.assertEqual(self.client.get(reverse("cuentas:logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("cuentas:logout")), reverse("cuentas:login"))
        self.assertEqual(self.client.get(reverse("core:inicio")).status_code, 302)

    def test_credenciales_incorrectas_no_dan_acceso(self):
        response = self.client.post(reverse("cuentas:login"), {"username": "administradora", "password": "incorrecta"})
        self.assertContains(response, "Revisa tu usuario y contraseña")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_cuenta_inactiva_no_puede_entrar(self):
        self.usuario.is_active = False
        self.usuario.save(update_fields=["is_active"])
        self.client.post(reverse("cuentas:login"), {"username": "administradora", "password": "UnaClaveSoloParaPruebas123!"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_no_redirige_a_sitio_externo(self):
        response = self.client.post(reverse("cuentas:login"), {
            "username": "administradora", "password": "UnaClaveSoloParaPruebas123!", "next": "https://example.invalid/",
        })
        self.assertRedirects(response, reverse("core:inicio"))

    def test_login_y_logout_requieren_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse("cuentas:login"), {"username": "administradora", "password": "UnaClaveSoloParaPruebas123!"}).status_code, 403)
        client.force_login(self.usuario)
        self.assertEqual(client.post(reverse("cuentas:logout")).status_code, 403)

    def test_inicio_usa_fecha_local_configurada(self):
        actualizar_configuracion(actor=self.usuario, nombre="Salón HM", zona_horaria="America/Tijuana")
        self.client.force_login(self.usuario)
        # A las 02:00 UTC del día 8 todavía es día 7 en Tijuana.
        with patch("django.utils.timezone.now", return_value=datetime(2026, 10, 8, 2, tzinfo=datetime_timezone.utc)):
            response = self.client.get(reverse("core:inicio"))
        self.assertEqual(str(response.context["fecha_local"]), "2026-10-07")
        self.assertContains(response, "America/Tijuana")

    def test_no_existe_registro_publico(self):
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get("/cuenta/registro/").status_code, 404)


class HealthTests(TestCase):
    def test_health_es_publico_y_consulta_postgresql(self):
        response = self.client.get(reverse("core:health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_health_falla_sin_exponer_detalles(self):
        with patch("apps.core.views.connection.cursor", side_effect=OperationalError("detalle privado")):
            response = self.client.get(reverse("core:health"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
        self.assertNotContains(response, "detalle privado", status_code=503)

