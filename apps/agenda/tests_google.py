from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo
import uuid

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.integraciones.crypto import ErrorGoogle, cifrar
from apps.integraciones.google import GoogleCalendar
from apps.integraciones.models import ConexionGoogle, VinculoEventoGoogle

from .models import Cita


ZONA = ZoneInfo("America/Merida")


@override_settings(GOOGLE_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
class EventosAgendaTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(username="Marisol", password="SoloPruebas123!")
        self.conexion = ConexionGoogle.objects.create(usuario=self.actor, calendario_id="principal-prueba", cuenta="principal-prueba", calendario_nombre="Salón", credenciales_cifradas=cifrar("{}"))
        self.inicio = datetime(2026, 10, 10, 15, tzinfo=ZONA)
        self.evento = {"id": "evento-prueba", "titulo": "Doña lurdes", "inicio": self.inicio, "fin": self.inicio + timedelta(hours=1), "todo_el_dia": False, "url": "https://calendar.google.com/calendar/event?eid=prueba"}
        self.client.force_login(self.actor)

    def cita_local(self):
        cliente = Cliente.objects.create(nombre="Clienta local")
        return Cita.objects.create(cliente=cliente, responsable=self.actor, inicio=self.inicio, fin=self.inicio + timedelta(hours=1), motivo="Corte", clave_operacion=uuid.uuid4(), hash_operacion="hash-prueba")

    def test_dia_y_semana_muestran_evento_sin_crear_clientas_o_citas(self):
        for vista in ("dia", "semana"):
            with patch("apps.agenda.lectura_google.GoogleCalendar") as adapter:
                adapter.return_value.eventos.return_value = [self.evento]
                response = self.client.get(reverse("agenda:listado"), {"fecha": "2026-10-10", "vista": vista})
                self.assertContains(response, "15:00–16:00 · Doña lurdes")
                self.assertContains(response, "Abrir en Google")
                adapter.return_value.close.assert_called_once()
                grupo = next(g for g in response.context["grupos"] if str(g["fecha"]) == "2026-10-10")
                self.assertEqual(len(grupo["entradas"]), 1)
        self.assertFalse(Cita.objects.exists())
        self.assertFalse(Cliente.objects.exists())

    def test_proximas_y_inicio_incluyen_google(self):
        with patch("apps.agenda.lectura_google.GoogleCalendar") as adapter, patch("django.utils.timezone.now", return_value=datetime(2026, 10, 10, 12, tzinfo=ZONA)):
            adapter.return_value.eventos.return_value = [self.evento]
            for url in [reverse("agenda:listado") + "?vista=proximas", reverse("core:inicio")]:
                response = self.client.get(url)
                self.assertContains(response, "Doña lurdes")
                self.assertContains(response, "Google Calendar")

    def test_copia_sincronizada_no_se_duplica_y_horario_movido_se_muestra(self):
        cita = self.cita_local()
        VinculoEventoGoogle.objects.create(cita=cita, conexion=self.conexion, calendario_id=self.conexion.calendario_id, evento_id=self.evento["id"])
        with patch("apps.agenda.lectura_google.GoogleCalendar") as adapter:
            adapter.return_value.eventos.return_value = [self.evento]
            response = self.client.get(reverse("agenda:listado"), {"fecha": "2026-10-10"})
            self.assertEqual(len(response.context["grupos"][0]["entradas"]), 1)
            adapter.return_value.eventos.return_value = [{**self.evento, "inicio": self.inicio + timedelta(hours=2), "fin": self.inicio + timedelta(hours=3)}]
            response = self.client.get(reverse("agenda:listado"), {"fecha": "2026-10-10"})
            self.assertEqual(len(response.context["grupos"][0]["entradas"]), 2)
            self.assertContains(response, "17:00–18:00")

    def test_error_google_conserva_citas_locales_y_no_afirma_agenda_vacia(self):
        self.cita_local()
        with patch("apps.agenda.lectura_google.GoogleCalendar") as adapter:
            adapter.return_value.eventos.side_effect = ErrorGoogle("No disponible")
            response = self.client.get(reverse("agenda:listado"), {"fecha": "2026-10-10", "vista": "semana"})
        self.assertContains(response, "Clienta local")
        self.assertContains(response, "Los eventos de Google están pendientes de comprobar")
        self.assertContains(response, "No se pudieron consultar los eventos de Google")
        self.assertEqual(Cita.objects.count(), 1)

    def test_evento_todo_el_dia_no_aparece_en_fecha_final_exclusiva(self):
        evento = {**self.evento, "inicio": datetime(2026, 10, 9, tzinfo=ZONA), "fin": datetime(2026, 10, 11, tzinfo=ZONA), "todo_el_dia": True}
        with patch("apps.agenda.lectura_google.GoogleCalendar") as adapter:
            adapter.return_value.eventos.return_value = [evento]
            response = self.client.get(reverse("agenda:listado"), {"fecha": "2026-10-10", "vista": "semana"})
        grupos = {str(g["fecha"]): len(g["entradas"]) for g in response.context["grupos"]}
        self.assertEqual(grupos["2026-10-09"], 1)
        self.assertEqual(grupos["2026-10-10"], 1)
        self.assertEqual(grupos["2026-10-11"], 0)
        self.assertContains(response, "Todo el día")

    def test_cuenta_de_otro_usuario_no_se_consulta(self):
        otro = get_user_model().objects.create_superuser(username="Otra", password="SoloPruebas123!")
        self.client.force_login(otro)
        with patch("apps.agenda.lectura_google.GoogleCalendar") as adapter:
            response = self.client.get(reverse("agenda:listado"), {"fecha": "2026-10-10"})
        adapter.assert_not_called()
        self.assertNotContains(response, "Doña lurdes")

    def test_titulo_html_se_escapa(self):
        with patch("apps.agenda.lectura_google.GoogleCalendar") as adapter:
            adapter.return_value.eventos.return_value = [{**self.evento, "titulo": "<script>alert('x')</script>"}]
            response = self.client.get(reverse("agenda:listado"), {"fecha": "2026-10-10"})
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert('x')</script>")

    def test_conexion_vencida_no_se_presenta_como_sin_citas(self):
        self.conexion.requiere_autorizacion = True
        self.conexion.save()
        with patch("apps.agenda.lectura_google.GoogleCalendar") as adapter:
            response = self.client.get(reverse("agenda:listado"), {"fecha": "2026-10-10"})
        adapter.assert_not_called()
        self.assertContains(response, "Reconecta tu cuenta de Google")

    def test_adaptador_paginacion_utc_recurrencias_cancelados_y_enlaces(self):
        with patch("apps.integraciones.google.AuthorizedSession"):
            adapter = GoogleCalendar(self.conexion, credentials=object())
        payload = {"id": "evento", "summary": "Doña lurdes", "start": {"dateTime": "2026-10-10T21:00:00Z"}, "end": {"dateTime": "2026-10-10T22:00:00Z"}, "htmlLink": "javascript:alert(1)"}
        try:
            with patch.object(adapter, "request", side_effect=[(200, {"items": [{"status": "cancelled"}], "nextPageToken": "pagina-2"}), (200, {"items": [payload]})]) as request:
                eventos = adapter.eventos(datetime(2026, 10, 10, tzinfo=ZONA), datetime(2026, 10, 11, tzinfo=ZONA))
            self.assertEqual(len(eventos), 1)
            self.assertEqual(eventos[0]["inicio"].astimezone(ZONA).hour, 15)
            self.assertEqual(eventos[0]["url"], "")
            params = request.call_args.kwargs["params"]
            self.assertEqual(params["singleEvents"], "true")
            self.assertEqual(params["pageToken"], "pagina-2")
            self.assertNotIn("description", params["fields"])
            self.assertNotIn("attendees", params["fields"])
        finally:
            adapter.close()

    def test_adaptador_all_day_y_horario_invalido(self):
        with patch("apps.integraciones.google.AuthorizedSession"):
            adapter = GoogleCalendar(self.conexion, credentials=object())
        payload = {"id": "evento", "start": {"date": "2026-10-10"}, "end": {"date": "2026-10-11"}}
        try:
            with patch.object(adapter, "request", return_value=(200, {"items": [payload]})):
                eventos = adapter.eventos(datetime(2026, 10, 10, tzinfo=ZONA), datetime(2026, 10, 11, tzinfo=ZONA))
            self.assertTrue(eventos[0]["todo_el_dia"])
            self.assertEqual(eventos[0]["titulo"], "Evento sin título")
            payload["end"] = {"date": "2026-10-09"}
            with patch.object(adapter, "request", return_value=(200, {"items": [payload]})), self.assertRaises(ErrorGoogle):
                adapter.eventos(datetime(2026, 10, 10, tzinfo=ZONA), datetime(2026, 10, 11, tzinfo=ZONA))
        finally:
            adapter.close()

    def test_actualizacion_parcial_conserva_fecha_y_muestra_cambios_google(self):
        with patch("apps.agenda.lectura_google.GoogleCalendar") as adapter:
            adapter.return_value.eventos.return_value = [self.evento]
            response = self.client.get(reverse("agenda:listado"), {"fecha": "2026-10-10", "vista": "semana"}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="agenda-eventos")
            self.assertContains(response, 'id="agenda-eventos"')
            self.assertContains(response, "Doña lurdes")
            self.assertContains(response, "every 60s [!document.hidden]")
            self.assertNotContains(response, "<!doctype html>")
            self.assertNotContains(response, 'id="fecha-agenda"')
            self.assertIn("HX-Request", response["Vary"])
            self.assertIn("no-store", response["Cache-Control"])
            self.assertEqual(len(response.context["grupos"]), 7)
            adapter.return_value.eventos.return_value = [{**self.evento, "titulo": "Nuevo evento", "inicio": self.inicio + timedelta(hours=2), "fin": self.inicio + timedelta(hours=3)}]
            actualizada = self.client.get(reverse("agenda:listado"), {"fecha": "2026-10-10"}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="agenda-eventos")
            self.assertContains(actualizada, "Nuevo evento")
            self.assertContains(actualizada, "17:00–18:00")

    def test_actualizacion_inicio_es_fragmento_y_no_crea_registros(self):
        with patch("apps.agenda.lectura_google.GoogleCalendar") as adapter, patch("django.utils.timezone.now", return_value=datetime(2026, 10, 10, 12, tzinfo=ZONA)):
            adapter.return_value.eventos.return_value = [self.evento]
            response = self.client.get(reverse("core:inicio"), HTTP_HX_REQUEST="true", HTTP_HX_TARGET="citas-hoy")
        self.assertContains(response, 'id="citas-hoy"')
        self.assertContains(response, "Doña lurdes")
        self.assertNotContains(response, "<!doctype html>")
        self.assertFalse(Cita.objects.exists())
        self.assertFalse(Cliente.objects.exists())

    def test_sesion_caducada_redirige_sin_insertar_login_en_agenda(self):
        self.client.logout()
        for url, objetivo in [(reverse("agenda:listado"), "agenda-eventos"), (reverse("core:inicio"), "citas-hoy")]:
            response = self.client.get(url, HTTP_HX_REQUEST="true", HTTP_HX_TARGET=objetivo)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response["HX-Redirect"], reverse("cuentas:login"))
            self.assertEqual(response.content, b"")
            self.assertIn("no-store", response["Cache-Control"])
