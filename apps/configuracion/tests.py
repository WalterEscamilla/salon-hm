from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from apps.auditoria.models import EventoAuditoria

from .models import ConfiguracionSalon
from .services import actualizar_configuracion


class ConfiguracionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(username="admin", email="admin@example.invalid", password="PruebaSegura123!")
        cls.usuario = get_user_model().objects.create_user(username="sinpermisos", password="PruebaSegura123!")

    def test_migracion_crea_configuracion_unica(self):
        salon = ConfiguracionSalon.objects.get(pk=1)
        self.assertEqual(salon.nombre, "Salón HM")
        self.assertEqual(salon.zona_horaria, "America/Merida")
        self.assertEqual(salon.moneda, "MXN")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ConfiguracionSalon.objects.create(id=2)

    def test_guardar_configuracion_crea_auditoria(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("configuracion:editar"), {"nombre": "Salón HM prueba", "zona_horaria": "America/Cancun"})
        self.assertRedirects(response, reverse("configuracion:editar"))
        salon = ConfiguracionSalon.objects.get(pk=1)
        self.assertEqual(salon.zona_horaria, "America/Cancun")
        self.assertEqual(salon.nombre, "Salón HM prueba")
        evento = EventoAuditoria.objects.get()
        self.assertEqual(evento.actor, self.admin)
        self.assertEqual(evento.cambios["antes"]["zona_horaria"], "America/Merida")
        self.assertEqual(evento.origen, "formulario")
        self.assertIsNotNone(salon.actualizado_en.utcoffset())

    def test_zona_invalida_no_guarda_ni_audita(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("configuracion:editar"), {"nombre": "Cambio inválido", "zona_horaria": "Zona/Inexistente"})
        self.assertContains(response, "Escribe una zona válida")
        self.assertEqual(ConfiguracionSalon.objects.get(pk=1).nombre, "Salón HM")
        self.assertFalse(EventoAuditoria.objects.exists())

    def test_servicio_revalida_zona_sin_formulario(self):
        with self.assertRaises(ValidationError):
            actualizar_configuracion(actor=self.admin, nombre="No guardar", zona_horaria="Zona/Inexistente")
        self.assertEqual(ConfiguracionSalon.objects.get(pk=1).nombre, "Salón HM")

    def test_permiso_se_valida_en_vista_y_servicio(self):
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("configuracion:editar")).status_code, 403)
        with self.assertRaises(PermissionDenied):
            actualizar_configuracion(actor=self.usuario, nombre="No permitido", zona_horaria="America/Merida")

    def test_post_de_configuracion_requiere_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.post(reverse("configuracion:editar"), {"nombre": "No permitido", "zona_horaria": "America/Merida"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ConfiguracionSalon.objects.get(pk=1).nombre, "Salón HM")

    def test_cambio_se_revierte_si_falla_auditoria(self):
        with patch("apps.configuracion.services.EventoAuditoria.objects.create", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                actualizar_configuracion(actor=self.admin, nombre="Debe revertirse", zona_horaria="America/Cancun")
        salon = ConfiguracionSalon.objects.get(pk=1)
        self.assertEqual(salon.nombre, "Salón HM")
        self.assertEqual(salon.zona_horaria, "America/Merida")

