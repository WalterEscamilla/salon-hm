from datetime import datetime, timedelta
import uuid
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.atenciones.models import Atencion
from apps.auditoria.models import EventoAuditoria
from apps.clientes.models import Cliente
from apps.integraciones.crypto import ErrorGoogle, cifrar
from apps.integraciones.models import ConexionGoogle, TrabajoSincronizacion, VinculoEventoGoogle
from apps.integraciones.services import aplicar_eliminacion_google
from .models import Cita, RegistroServicioAgenda

ZONA = ZoneInfo("America/Merida")


@override_settings(GOOGLE_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
class EliminacionGoogleTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(username="Marisol", password="SoloPruebas123!")
        self.cliente = Cliente.objects.create(nombre="Clienta de prueba")
        self.conexion = ConexionGoogle.objects.create(
            usuario=self.actor, calendario_id="calendario-prueba", cuenta="calendario-prueba",
            credenciales_cifradas=cifrar("{}"),
        )
        self.inicio = datetime(2026, 10, 10, 15, tzinfo=ZONA)
        self.cita = Cita.objects.create(
            cliente=self.cliente, responsable=self.actor, inicio=self.inicio,
            fin=self.inicio + timedelta(hours=1), motivo="Corte", hash_operacion="prueba",
            sincronizacion=Cita.Sincronizacion.SINCRONIZADA,
        )
        self.vinculo = VinculoEventoGoogle.objects.create(
            cita=self.cita, conexion=self.conexion, calendario_id=self.conexion.calendario_id,
            evento_id="evento-publicado", etag='"anterior"', version_sincronizada=1,
        )
        self.client.force_login(self.actor)

    def agenda(self, **parametros):
        return self.client.get(reverse("agenda:listado"), {"fecha": "2026-10-10", **parametros})

    @patch("apps.agenda.lectura_google.GoogleCalendar")
    def test_eliminada_desaparece_en_dia_semana_proximas_e_inicio_sin_borrar_registros(self, google):
        google.return_value.eventos.return_value = []
        google.return_value.obtener_evento.return_value = {"id": self.vinculo.evento_id, "status": "cancelled", "etag": '"eliminado"'}
        for vista in ("dia", "semana"):
            self.assertNotContains(self.agenda(vista=vista), "Clienta de prueba")
        with patch("django.utils.timezone.now", return_value=self.inicio - timedelta(hours=1)):
            self.assertNotContains(self.agenda(vista="proximas"), "Clienta de prueba")
            self.assertNotContains(self.client.get(reverse("core:inicio")), "Clienta de prueba")
        self.cita.refresh_from_db()
        self.vinculo.refresh_from_db()
        self.assertEqual(self.cita.estado, Cita.Estado.CANCELADA)
        self.assertEqual(self.cita.version, 2)
        self.assertEqual(self.cita.sincronizacion, Cita.Sincronizacion.SINCRONIZADA)
        self.assertTrue(self.vinculo.cancelado)
        self.assertEqual(Cita.objects.count(), 1)
        self.assertEqual(EventoAuditoria.objects.filter(operacion="google.evento_eliminado").count(), 1)
        google.return_value.publicar.assert_not_called()

    @patch("apps.agenda.lectura_google.GoogleCalendar")
    def test_404_o_410_confirmado_por_id_retira_la_cita(self, google):
        google.return_value.eventos.return_value = []
        google.return_value.obtener_evento.return_value = None
        self.assertNotContains(self.agenda(), "Clienta de prueba")
        google.return_value.obtener_evento.assert_called_once_with(self.conexion.calendario_id, self.vinculo.evento_id)
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, Cita.Estado.CANCELADA)

    @patch("apps.agenda.lectura_google.GoogleCalendar")
    def test_movida_fuera_del_intervalo_no_se_cancela(self, google):
        google.return_value.eventos.return_value = []
        google.return_value.obtener_evento.return_value = {"id": self.vinculo.evento_id, "status": "confirmed"}
        self.assertContains(self.agenda(), "Clienta de prueba")
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, Cita.Estado.PENDIENTE)
        self.assertFalse(EventoAuditoria.objects.filter(operacion="google.evento_eliminado").exists())

    @patch("apps.agenda.lectura_google.GoogleCalendar")
    def test_error_de_google_conserva_la_cita(self, google):
        google.return_value.eventos.return_value = []
        google.return_value.obtener_evento.side_effect = ErrorGoogle("No se pudo comprobar Google")
        response = self.agenda()
        self.assertContains(response, "Clienta de prueba")
        self.assertContains(response, "No se pudo comprobar Google")
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.version, 1)
        self.assertEqual(self.cita.estado, Cita.Estado.PENDIENTE)

    @patch("apps.agenda.lectura_google.GoogleCalendar")
    def test_cita_nunca_publicada_no_se_confunde_con_eliminacion(self, google):
        self.vinculo.version_sincronizada = 0
        self.vinculo.save(update_fields=["version_sincronizada"])
        google.return_value.eventos.return_value = []
        self.assertContains(self.agenda(), "Clienta de prueba")
        google.return_value.obtener_evento.assert_not_called()
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, Cita.Estado.PENDIENTE)

    def test_otro_usuario_u_otro_calendario_no_pueden_cancelar(self):
        otro = get_user_model().objects.create_superuser(username="Otra", password="SoloPruebas123!")
        self.assertIsNone(aplicar_eliminacion_google(self.vinculo, cita_version=1, actor=otro, evento=None))
        self.conexion.calendario_id = "otro-calendario"
        self.conexion.save(update_fields=["calendario_id"])
        self.assertIsNone(aplicar_eliminacion_google(self.vinculo, cita_version=1, actor=self.actor, evento=None))
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, Cita.Estado.PENDIENTE)

    def test_respuesta_anterior_no_revierte_edicion_o_sincronizacion_nueva(self):
        Cita.objects.filter(pk=self.cita.pk).update(version=2)
        self.assertIsNone(aplicar_eliminacion_google(self.vinculo, cita_version=1, actor=self.actor, evento=None))
        VinculoEventoGoogle.objects.filter(pk=self.vinculo.pk).update(etag='"nuevo"')
        self.assertIsNone(aplicar_eliminacion_google(self.vinculo, cita_version=2, actor=self.actor, evento=None))
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, Cita.Estado.PENDIENTE)

    def test_anula_trabajos_pendientes_y_respuestas_tardias(self):
        trabajo = TrabajoSincronizacion.objects.create(
            cita=self.cita, conexion=self.conexion, version=1, estado="procesando",
            token_bloqueo=uuid.uuid4(), bloqueo_hasta=self.inicio, proximo_intento=self.inicio,
        )
        self.assertIsNotNone(aplicar_eliminacion_google(self.vinculo, cita_version=1, actor=self.actor, evento=None))
        trabajo.refresh_from_db()
        self.assertEqual(trabajo.estado, TrabajoSincronizacion.Estado.OBSOLETO)
        self.assertIsNone(trabajo.token_bloqueo)
        self.assertIsNone(trabajo.bloqueo_hasta)

    @patch("apps.agenda.lectura_google.GoogleCalendar")
    def test_atencion_completada_y_registro_se_conservan(self, google):
        self.cita.estado = Cita.Estado.COMPLETADA
        self.cita.save(update_fields=["estado"])
        atencion = Atencion.objects.create(
            cliente=self.cliente, fecha=self.inicio.date(), servicio="Corte",
            actor=self.actor, huella_operacion="prueba",
        )
        registro = RegistroServicioAgenda.objects.create(cita=self.cita, atencion=atencion, usuario=self.actor)
        google.return_value.eventos.return_value = []
        google.return_value.obtener_evento.return_value = None
        self.assertNotContains(self.agenda(), "Clienta de prueba")
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, Cita.Estado.COMPLETADA)
        self.assertTrue(Atencion.objects.filter(pk=atencion.pk).exists())
        self.assertTrue(RegistroServicioAgenda.objects.filter(pk=registro.pk).exists())
