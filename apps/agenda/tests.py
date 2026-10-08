from datetime import timedelta
from decimal import Decimal
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.auditoria.models import EventoAuditoria
from apps.catalogos.models import Servicio
from apps.clientes.models import Cliente

from .forms import CitaForm
from .models import Cita
from .services import AdvertenciaTraslape, guardar_cita


class AgendaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="Marisol", password="ClaveParaPruebas123!")
        cls.cliente = Cliente.objects.create(nombre="Ana López", telefono="9991112233")
        cls.homonima = Cliente.objects.create(nombre="Ana López", telefono="9994445566")
        cls.servicio = Servicio.objects.create(nombre="Corte", duracion_minutos=45, precio_base=Decimal("250.00"))

    def datos(self, **changes):
        inicio = timezone.now().replace(second=0, microsecond=0) + timedelta(days=1)
        datos = {"cliente": self.cliente, "servicios": [], "motivo": "Corte", "inicio": inicio, "fin": inicio + timedelta(hours=1), "notas": "Nota privada", "estado": Cita.Estado.PENDIENTE, "clave_operacion": uuid.uuid4(), "version": None, "aceptar_traslape": False, "confirmacion_traslape": ""}
        datos.update(changes)
        return datos

    def guardar(self, datos, **extra):
        return guardar_cita(actor=self.actor, datos=datos, sesion="sesion-prueba", **extra)

    def test_guardar_cita_sin_catalogo_y_homonimos_por_id(self):
        cita = self.guardar(self.datos(cliente=self.homonima))
        self.assertEqual(cita.cliente_id, self.homonima.pk)
        self.assertEqual(cita.sincronizacion, "sin_conexion")
        self.assertEqual(Cita.objects.count(), 1)
        etiquetas = [label for _, label in CitaForm().fields["cliente"].choices]
        self.assertTrue(any("9991112233" in str(label) for label in etiquetas))
        self.assertTrue(any("9994445566" in str(label) for label in etiquetas))

    def test_doble_click_no_duplica_cita_ni_auditoria(self):
        datos = self.datos()
        primera = self.guardar(datos)
        segunda = self.guardar(datos)
        self.assertEqual(primera.pk, segunda.pk)
        self.assertEqual(Cita.objects.count(), 1)
        self.assertEqual(EventoAuditoria.objects.filter(operacion="cita.creada").count(), 1)
        with self.assertRaises(ValidationError):
            self.guardar({**datos, "motivo": "Otro servicio"})

    def test_traslape_exige_advertencia_y_confirmacion_exacta(self):
        datos = self.datos()
        self.guardar(datos)
        nuevos = {**datos, "clave_operacion": uuid.uuid4(), "cliente": self.homonima}
        with self.assertRaises(AdvertenciaTraslape) as context:
            self.guardar(nuevos)
        self.assertEqual(Cita.objects.count(), 1)
        self.guardar({**nuevos, "aceptar_traslape": True, "confirmacion_traslape": context.exception.confirmacion})
        self.assertEqual(Cita.objects.count(), 2)

    def test_aceptacion_no_aplica_a_datos_o_sesion_diferentes(self):
        datos = self.datos()
        self.guardar(datos)
        nuevos = {**datos, "clave_operacion": uuid.uuid4()}
        with self.assertRaises(AdvertenciaTraslape) as context:
            self.guardar(nuevos)
        confirmados = {**nuevos, "aceptar_traslape": True, "confirmacion_traslape": context.exception.confirmacion}
        with self.assertRaises(AdvertenciaTraslape):
            self.guardar({**confirmados, "notas": "Datos nuevos"})
        with self.assertRaises(AdvertenciaTraslape):
            guardar_cita(actor=self.actor, datos=confirmados, sesion="otra-sesion")

    def test_citas_adyacentes_y_canceladas_no_traslapan(self):
        datos = self.datos()
        self.guardar(datos)
        self.guardar({**datos, "clave_operacion": uuid.uuid4(), "inicio": datos["fin"], "fin": datos["fin"] + timedelta(hours=1)})
        self.guardar({**datos, "clave_operacion": uuid.uuid4(), "estado": "cancelada"})
        self.assertEqual(Cita.objects.count(), 3)

    def test_edicion_no_permite_sobrescribir_version_vieja(self):
        datos = self.datos()
        cita = self.guardar(datos)
        self.guardar({**datos, "version": 1, "estado": "confirmada"}, cita_id=cita.pk)
        with self.assertRaises(ValidationError):
            self.guardar({**datos, "version": 1}, cita_id=cita.pk)

    def test_servicio_previsto_conserva_nombre_y_duracion(self):
        datos = self.datos(servicios=[self.servicio])
        cita = self.guardar(datos)
        self.servicio.nombre = "Nombre nuevo"
        self.servicio.duracion_minutos = 90
        self.servicio.save()
        self.guardar({**datos, "version": 1}, cita_id=cita.pk)
        previsto = cita.servicios_previstos.get()
        self.assertEqual(previsto.nombre, "Corte")
        self.assertEqual(previsto.duracion_minutos, 45)

    def test_validacion_backend_de_horario_y_permisos(self):
        datos = self.datos()
        with self.assertRaises(ValidationError):
            self.guardar({**datos, "fin": datos["inicio"]})
        with self.assertRaises(ValidationError):
            self.guardar({**datos, "inicio": datos["inicio"].replace(tzinfo=None)})
        actor = get_user_model().objects.create_user(username="sin-permisos")
        with self.assertRaises(PermissionDenied):
            guardar_cita(actor=actor, datos=datos, sesion="sesion-prueba")

    def test_formulario_y_vistas_completas(self):
        self.client.force_login(self.actor)
        datos = self.datos()
        response = self.client.post(reverse("agenda:nueva"), {"cliente": self.homonima.pk, "motivo": "Corte", "inicio": timezone.localtime(datos["inicio"]).strftime("%Y-%m-%dT%H:%M"), "fin": timezone.localtime(datos["fin"]).strftime("%Y-%m-%dT%H:%M"), "estado": "pendiente", "clave_operacion": str(datos["clave_operacion"]), "notas": ""})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(response.url), "Ana López")
        for vista in ["dia", "semana", "proximas"]:
            with self.subTest(vista=vista):
                self.assertEqual(self.client.get(reverse("agenda:listado"), {"vista": vista}).status_code, 200)

    def test_falla_auditoria_revierte_cita(self):
        with patch("apps.agenda.services.EventoAuditoria.objects.create", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                self.guardar(self.datos())
        self.assertFalse(Cita.objects.exists())

