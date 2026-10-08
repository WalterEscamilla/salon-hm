from datetime import timedelta
import json
import logging
import uuid
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.agenda.models import Cita
from apps.agenda.services import guardar_cita
from apps.clientes.models import Cliente

from .crypto import ErrorGoogle, ConflictoGoogle, cifrar, descifrar
from .logging import OAuthQueryFilter
from .models import ConexionGoogle, TrabajoSincronizacion, VinculoEventoGoogle
from .services import payload_cita, procesar_trabajo


@override_settings(GOOGLE_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
class GoogleTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(username="Marisol", password="SoloPruebas123!")
        self.cliente = Cliente.objects.create(nombre="Nombre privado")
        self.conexion = ConexionGoogle.objects.create(usuario=self.actor, credenciales_cifradas=cifrar('{"refresh_token": "token-ficticio"}'), cuenta="cuenta-prueba", calendario_id="calendario-prueba", calendario_nombre="Salón HM")

    def cita(self):
        inicio = timezone.now() + timedelta(days=1)
        return guardar_cita(actor=self.actor, sesion="sesion", datos={"cliente": self.cliente, "servicios": [], "motivo": "Tinte", "inicio": inicio, "fin": inicio + timedelta(hours=1), "notas": "Fórmula privada", "estado": "pendiente", "clave_operacion": uuid.uuid4()})

    def adapter(self, mock):
        adapter = mock.return_value
        adapter.obtener_evento.return_value = None
        adapter.publicar.return_value = {"etag": '"version-1"'}
        return adapter

    def test_tokens_cifrados_y_payload_sin_informacion_privada(self):
        self.assertNotIn("token-ficticio", self.conexion.credenciales_cifradas)
        self.assertIn("token-ficticio", descifrar(self.conexion.credenciales_cifradas))
        payload = json.dumps(payload_cita(self.cita(), "hm123456"), ensure_ascii=False)
        self.assertNotIn("Nombre privado", payload)
        self.assertNotIn("Fórmula privada", payload)
        self.assertNotIn("attendees", payload)

    def adapter_con_credenciales_ficticias(self):
        from .google import GoogleCalendar
        self.conexion.credenciales_cifradas = cifrar(json.dumps({"refresh_token": "refresh-ficticio", "client_id": "id-ficticio", "client_secret": "secreto-ficticio", "token": "token-ficticio", "expiry": "2050-01-01T00:00:00Z"}))
        self.conexion.save()
        return GoogleCalendar(self.conexion)

    def test_adaptador_real_aplica_timeout_y_etag_sin_red(self):
        adapter = self.adapter_con_credenciales_ficticias()
        try:
            response = MagicMock(status_code=412)
            with patch.object(adapter.session, "request", return_value=response) as request:
                with self.assertRaises(ConflictoGoogle):
                    adapter.request("PUT", "ruta-ficticia", etag='"etag-ficticio"')
                self.assertEqual(request.call_args.kwargs["timeout"], 10)
                self.assertEqual(request.call_args.kwargs["headers"]["If-Match"], '"etag-ficticio"')
        finally:
            adapter.close()

    def test_revocacion_exige_reautorizar_sin_exponer_token(self):
        from google.auth.exceptions import RefreshError
        adapter = self.adapter_con_credenciales_ficticias()
        try:
            with patch.object(adapter.session, "request", side_effect=RefreshError("secreto que no debe mostrarse")):
                with self.assertRaises(ErrorGoogle) as context:
                    adapter.request("GET", "ruta-ficticia")
            self.assertNotIn("secreto que no debe mostrarse", str(context.exception))
            self.conexion.refresh_from_db()
            self.assertTrue(self.conexion.requiere_autorizacion)
        finally:
            adapter.close()

    def respuesta_error(self, status, razon, *, moderno=False):
        response = MagicMock(status_code=status)
        campo = "details" if moderno else "errors"
        response.json.return_value = {"error": {"message": "mensaje privado no debe mostrarse", campo: [{"reason": razon, "metadata": {"secreto": "no debe mostrarse"}}]}}
        return response

    def test_api_deshabilitada_se_distingue_de_permisos_y_no_revoca_conexion(self):
        for razon, moderno in [("accessNotConfigured", False), ("SERVICE_DISABLED", True)]:
            adapter = self.adapter_con_credenciales_ficticias()
            try:
                with patch.object(adapter.session, "request", return_value=self.respuesta_error(403, razon, moderno=moderno)):
                    with self.assertRaises(ErrorGoogle) as context:
                        adapter.calendarios()
                self.assertEqual(context.exception.codigo, "api_no_habilitada")
                self.assertIn("Habilitar", str(context.exception))
                self.assertNotIn("privado", str(context.exception))
                self.conexion.refresh_from_db()
                self.assertFalse(self.conexion.requiere_autorizacion)
            finally:
                adapter.close()

    def test_permisos_insuficientes_marcan_reautorizacion(self):
        adapter = self.adapter_con_credenciales_ficticias()
        try:
            with patch.object(adapter.session, "request", return_value=self.respuesta_error(403, "ACCESS_TOKEN_SCOPE_INSUFFICIENT", moderno=True)):
                with self.assertRaises(ErrorGoogle) as context:
                    adapter.calendarios()
            self.assertEqual(context.exception.codigo, "permisos_insuficientes")
            self.conexion.refresh_from_db()
            self.assertTrue(self.conexion.requiere_autorizacion)
        finally:
            adapter.close()

    def test_limites_403_y_429_no_requieren_reconectar(self):
        for status in (403, 429):
            adapter = self.adapter_con_credenciales_ficticias()
            try:
                with patch.object(adapter.session, "request", return_value=self.respuesta_error(status, "rateLimitExceeded")):
                    with self.assertRaises(ErrorGoogle) as context:
                        adapter.calendarios()
                self.assertEqual(context.exception.codigo, "limite_temporal")
                self.conexion.refresh_from_db()
                self.assertFalse(self.conexion.requiere_autorizacion)
            finally:
                adapter.close()

    def test_error_401_marca_reautorizacion(self):
        adapter = self.adapter_con_credenciales_ficticias()
        try:
            with patch.object(adapter.session, "request", return_value=self.respuesta_error(401, "authError")):
                with self.assertRaises(ErrorGoogle) as context:
                    adapter.calendarios()
            self.assertEqual(context.exception.codigo, "autorizacion_vencida")
            self.conexion.refresh_from_db()
            self.assertTrue(self.conexion.requiere_autorizacion)
        finally:
            adapter.close()

    def test_cuerpo_error_invalido_y_logs_no_exponen_datos(self):
        from .google import causa_error
        for cuerpo in [[], {"error": "texto"}, {"error": {"details": None}}, {"error": {"errors": [{"reason": {}}]}}]:
            response = MagicMock(status_code=403)
            response.json.return_value = cuerpo
            self.assertEqual(causa_error(response), "desconocida")
        adapter = self.adapter_con_credenciales_ficticias()
        try:
            with patch.object(adapter.session, "request", return_value=self.respuesta_error(403, "accessNotConfigured")), self.assertLogs("apps.integraciones.google", level="WARNING") as logs:
                with self.assertRaises(ErrorGoogle):
                    adapter.calendarios()
            self.assertIn("api_no_habilitada", logs.output[0])
            self.assertNotIn("privado", logs.output[0])
            self.assertNotIn("secreto", logs.output[0])
            self.assertNotIn("token-ficticio", logs.output[0])
        finally:
            adapter.close()

    @patch("apps.integraciones.views.GoogleCalendar")
    @patch("apps.integraciones.views.crear_flow")
    def test_callback_api_deshabilitada_muestra_causa_y_no_guarda_conexion(self, flow, google):
        self.conexion.delete()
        self.client.force_login(self.actor)
        session = self.client.session
        session["google_oauth"] = {"state": "correcto", "actor": self.actor.pk, "creado": timezone.now().timestamp(), "verifier": "verificador"}
        session.save()
        flow.return_value.credentials.granted_scopes = settings.GOOGLE_OAUTH_SCOPES
        google.return_value.calendarios.side_effect = ErrorGoogle("Google Calendar API no está habilitada en el proyecto. Pulsa Habilitar.", codigo="api_no_habilitada")
        response = self.client.get(reverse("integraciones:retorno"), {"state": "correcto", "code": "codigo-ficticio"}, follow=True)
        self.assertContains(response, "Google Calendar API no está habilitada")
        self.assertFalse(ConexionGoogle.objects.exists())
        self.assertNotIn("google_oauth", self.client.session)

    @patch("apps.integraciones.services.GoogleCalendar")
    def test_sincronizar_y_reintentar_no_duplica(self, mock):
        adapter = self.adapter(mock)
        cita = self.cita()
        trabajo = TrabajoSincronizacion.objects.get(cita=cita)
        self.assertTrue(procesar_trabajo(trabajo.pk))
        self.assertFalse(procesar_trabajo(trabajo.pk))
        self.assertEqual(adapter.publicar.call_count, 1)
        self.assertEqual(VinculoEventoGoogle.objects.count(), 1)
        cita.refresh_from_db()
        self.assertEqual(cita.sincronizacion, "sincronizada")

    @patch("apps.integraciones.services.GoogleCalendar")
    def test_google_falla_y_cita_no_se_pierde(self, mock):
        self.adapter(mock).obtener_evento.side_effect = ErrorGoogle("Google no disponible")
        cita = self.cita()
        trabajo = TrabajoSincronizacion.objects.get(cita=cita)
        self.assertFalse(procesar_trabajo(trabajo.pk))
        cita.refresh_from_db()
        self.assertEqual(cita.sincronizacion, "error")
        self.assertEqual(Cita.objects.count(), 1)
        self.assertEqual(cita.notas, "Fórmula privada")

    @patch("apps.integraciones.services.GoogleCalendar")
    def test_error_largo_se_guarda_y_permite_reintento(self, mock):
        self.adapter(mock).obtener_evento.side_effect = ErrorGoogle("Google no disponible. " * 30)
        cita = self.cita()
        trabajo = TrabajoSincronizacion.objects.get(cita=cita)
        self.assertFalse(procesar_trabajo(trabajo.pk))
        trabajo.refresh_from_db()
        cita.refresh_from_db()
        self.assertEqual(trabajo.estado, TrabajoSincronizacion.Estado.ERROR)
        self.assertEqual(len(trabajo.error), 240)
        self.assertEqual(cita.error_sincronizacion, trabajo.error)
        self.assertEqual(trabajo.intentos, 1)
        self.assertIsNone(trabajo.bloqueo_hasta)

    @patch("apps.integraciones.services.GoogleCalendar")
    def test_recuperar_respuesta_perdida_reutiliza_evento(self, mock):
        adapter = self.adapter(mock)
        cita = self.cita()
        trabajo = TrabajoSincronizacion.objects.get(cita=cita)
        adapter.publicar.side_effect = ErrorGoogle("Respuesta perdida")
        self.assertFalse(procesar_trabajo(trabajo.pk))
        vinculo = VinculoEventoGoogle.objects.get(cita=cita)
        adapter.publicar.side_effect = None
        adapter.obtener_evento.return_value = {**payload_cita(cita, vinculo.evento_id), "etag": '"resultado-recuperado"'}
        trabajo.proximo_intento = timezone.now()
        trabajo.save()
        self.assertTrue(procesar_trabajo(trabajo.pk))
        self.assertEqual(adapter.publicar.call_count, 1)
        vinculo.refresh_from_db()
        self.assertEqual(vinculo.etag, '"resultado-recuperado"')

    @patch("apps.integraciones.services.GoogleCalendar")
    def test_cambio_externo_no_se_sobrescribe(self, mock):
        adapter = self.adapter(mock)
        cita = self.cita()
        trabajo = TrabajoSincronizacion.objects.get(cita=cita)
        procesar_trabajo(trabajo.pk)
        vinculo = VinculoEventoGoogle.objects.get(cita=cita)
        trabajo.estado = "pendiente"
        trabajo.proximo_intento = timezone.now()
        trabajo.save()
        adapter.obtener_evento.return_value = {**payload_cita(cita, vinculo.evento_id), "etag": '"version-externa"'}
        self.assertFalse(procesar_trabajo(trabajo.pk))
        self.assertEqual(adapter.publicar.call_count, 1)
        cita.refresh_from_db()
        self.assertEqual(cita.sincronizacion, "conflicto")

    @patch("apps.integraciones.services.GoogleCalendar")
    def test_version_local_obsoleta_no_se_publica(self, mock):
        cita = self.cita()
        trabajo = TrabajoSincronizacion.objects.get(cita=cita)
        Cita.objects.filter(pk=cita.pk).update(version=2)
        self.assertFalse(procesar_trabajo(trabajo.pk))
        mock.assert_not_called()
        trabajo.refresh_from_db()
        self.assertEqual(trabajo.estado, "obsoleto")

    def test_callback_rechaza_state_incorrecto_y_no_crea_tokens(self):
        self.client.force_login(self.actor)
        session = self.client.session
        session["google_oauth"] = {"state": "correcto", "actor": self.actor.pk, "creado": timezone.now().timestamp(), "verifier": "verificador"}
        session.save()
        with patch("apps.integraciones.views.crear_flow") as flow:
            response = self.client.get(reverse("integraciones:retorno"), {"state": "incorrecto", "code": "no-usar"})
        self.assertRedirects(response, reverse("integraciones:calendario"), fetch_redirect_response=False)
        flow.assert_not_called()

    @override_settings(GOOGLE_CLIENT_ID="id-prueba", GOOGLE_CLIENT_SECRET="secreto-ficticio")
    def test_inicio_oauth_real_genera_state_y_pkce_sin_llamadas_externas(self):
        from urllib.parse import urlsplit, parse_qs
        self.client.force_login(self.actor)
        response = self.client.post(reverse("integraciones:conectar"))
        self.assertEqual(response.status_code, 302)
        url = urlsplit(response.url)
        self.assertEqual(url.hostname, "accounts.google.com")
        params = parse_qs(url.query)
        self.assertEqual(params["state"][0], self.client.session["google_oauth"]["state"])
        self.assertTrue(params["code_challenge"][0])
        self.assertTrue(self.client.session["google_oauth"]["verifier"])
        self.assertEqual(params["redirect_uri"][0], settings.GOOGLE_REDIRECT_URI)

    @override_settings(GOOGLE_CLIENT_ID="id-prueba", GOOGLE_CLIENT_SECRET="secreto-ficticio")
    @patch("apps.integraciones.views.GoogleCalendar")
    @patch("apps.integraciones.views.crear_flow")
    def test_callback_autorizado_cifra_tokens_y_consumo_unico_state(self, mock_flow, mock_google):
        self.client.force_login(self.actor)
        session = self.client.session
        session["google_oauth"] = {"state": "correcto", "actor": self.actor.pk, "creado": timezone.now().timestamp(), "verifier": "verificador"}
        session.save()
        credentials = mock_flow.return_value.credentials
        credentials.granted_scopes = settings.GOOGLE_OAUTH_SCOPES
        credentials.refresh_token = "refresh-ficticio"
        credentials.to_json.return_value = '{"refresh_token":"refresh-ficticio"}'
        mock_google.return_value.calendarios.return_value = [{"id": "cuenta-prueba", "primary": True, "accessRole": "owner"}]
        self.client.get(reverse("integraciones:retorno"), {"state": "correcto", "code": "codigo-ficticio"})
        self.conexion.refresh_from_db()
        self.assertNotIn("refresh-ficticio", self.conexion.credenciales_cifradas)
        self.assertIn("refresh-ficticio", descifrar(self.conexion.credenciales_cifradas))
        self.assertNotIn("google_oauth", self.client.session)
        self.client.get(reverse("integraciones:retorno"), {"state": "correcto", "code": "codigo-ficticio"})
        self.assertEqual(mock_flow.call_count, 1)

    @patch("apps.integraciones.services.GoogleCalendar")
    def test_reencolar_hecho_no_lo_deja_pendiente(self, mock):
        from .services import encolar_cita
        self.adapter(mock)
        cita = self.cita()
        trabajo = TrabajoSincronizacion.objects.get(cita=cita)
        procesar_trabajo(trabajo.pk)
        cita.refresh_from_db()
        encolar_cita(cita, self.actor)
        cita.refresh_from_db()
        self.assertEqual(cita.sincronizacion, "sincronizada")
        self.assertEqual(TrabajoSincronizacion.objects.count(), 1)

    @patch("apps.integraciones.services.GoogleCalendar")
    def test_cancelar_exige_etag_y_no_crea_evento_nuevo(self, mock):
        adapter = self.adapter(mock)
        cita = self.cita()
        trabajo = TrabajoSincronizacion.objects.get(cita=cita)
        procesar_trabajo(trabajo.pk)
        Cita.objects.filter(pk=cita.pk).update(estado="cancelada", version=2)
        adapter.obtener_evento.return_value = {"etag": '"version-1"', "status": "confirmed"}
        trabajo2 = TrabajoSincronizacion.objects.create(cita=cita, conexion=self.conexion, version=2, proximo_intento=timezone.now())
        self.assertTrue(procesar_trabajo(trabajo2.pk))
        adapter.cancelar.assert_called_once()
        self.assertEqual(adapter.publicar.call_count, 1)

    def test_se_oculta_codigo_oauth_de_logs(self):
        record = logging.LogRecord("django.server", logging.INFO, "", 1, '"%s" %s %s', ("GET /calendario/google/retorno/?code=SECRETO&state=OTRO HTTP/1.1", 302, 0), None)
        OAuthQueryFilter().filter(record)
        self.assertNotIn("SECRETO", record.getMessage())
        self.assertNotIn("OTRO", record.getMessage())

    @override_settings(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="")
    def test_pantalla_sin_credenciales_explicita_y_rutas_privadas(self):
        self.conexion.activa = False
        self.conexion.save()
        self.client.force_login(self.actor)
        self.assertContains(self.client.get(reverse("integraciones:calendario")), "Primero configura el acceso de Google")
        self.client.logout()
        for url in [reverse("integraciones:calendario"), reverse("agenda:nueva"), reverse("clientes:listado")]:
            self.assertEqual(self.client.get(url).status_code, 302)
