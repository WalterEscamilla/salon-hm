from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
import uuid

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.atenciones.forms import AtencionForm
from apps.atenciones.models import Atencion
from apps.atenciones.tests import datos_visita
from apps.atenciones.services import guardar_atencion
from apps.auditoria.models import EventoAuditoria
from apps.clientes.models import Cliente
from apps.integraciones.crypto import ErrorGoogle, cifrar
from apps.integraciones.models import ConexionGoogle, VinculoEventoGoogle
from .models import Cita, RegistroServicioAgenda
from .registro import guardar_desde_agenda, url_registro_google
from .services import guardar_cita


@override_settings(GOOGLE_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
class RegistroAgendaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="Marisol", password="SoloPruebas123!")
        cls.clienta = Cliente.objects.create(nombre="Ana López", telefono="9991234567")

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.actor)
        self.inicio = timezone.make_aware(datetime.combine(timezone.localdate(), time(10)))
        self.cita = Cita.objects.create(cliente=self.clienta, responsable=self.actor, inicio=self.inicio, fin=self.inicio+timedelta(hours=1), motivo="Corte", hash_operacion="prueba")
        self.url = reverse("atenciones:nueva") + f"?cita={self.cita.pk}"

    def google(self):
        self.conexion = ConexionGoogle.objects.create(usuario=self.actor, calendario_id="calendario-prueba", credenciales_cifradas=cifrar("{}"))
        self.evento = {"id": "recurrente_20261008T160000Z", "summary": "Rosa López", "start": {"dateTime": self.inicio.isoformat()}, "end": {"dateTime": (self.inicio+timedelta(hours=1)).isoformat()}}
        self.evento_visible = {"id": self.evento["id"], "titulo": "Rosa López", "inicio": self.inicio, "fin": self.inicio+timedelta(hours=1), "todo_el_dia": False, "url": ""}
        return url_registro_google(self.conexion.calendario_id, self.evento["id"])

    def pagina_google(self, url):
        with patch("apps.agenda.registro.GoogleCalendar") as adapter:
            adapter.return_value.obtener_evento.return_value = self.evento
            response = self.client.get(url)
            adapter.return_value.close.assert_called_once()
            adapter.return_value.publicar.assert_not_called()
        return response

    def payload(self, pagina, **cambios):
        return {**datos_visita(), "cliente_id": self.clienta.pk, "servicio": "Corte realizado", "origen_agenda": pagina.context["origen_agenda"], "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value, **cambios}

    def test_boton_y_formulario_local_precargado_sin_escrituras(self):
        agenda = self.client.get(reverse("agenda:listado"))
        self.assertContains(agenda, self.url)
        self.assertContains(agenda, "Registrar servicio")
        pagina = self.client.get(self.url)
        self.assertEqual(pagina.context["form"].initial["cliente_id"], self.clienta.pk)
        self.assertEqual(pagina.context["form"].initial["servicio"], "Corte")
        self.assertEqual(pagina.context["form"].initial["fecha"], self.inicio.date())
        self.assertFalse(Atencion.objects.exists())
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, "pendiente")

    def test_guardar_visita_local_marca_hecho_y_actualizacion_parcial_lo_conserva(self):
        pagina = self.client.get(self.url)
        response = self.client.post(self.url, self.payload(pagina, precio_cobrado="120", materiales="Máquina 2 y tijera"))
        self.assertEqual(response.status_code, 302)
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, Cita.Estado.COMPLETADA)
        self.assertEqual(self.cita.version, 2)
        self.assertEqual(Atencion.objects.get().precio_cobrado, Decimal("120"))
        self.assertEqual(RegistroServicioAgenda.objects.get().cita_id, self.cita.pk)
        for headers in ({}, {"HTTP_HX_REQUEST": "true", "HTTP_HX_TARGET": "agenda-eventos"}):
            agenda = self.client.get(reverse("agenda:listado"), **headers)
            self.assertContains(agenda, "✓ Hecho")
            self.assertContains(agenda, "Ver servicio")
            self.assertNotContains(agenda, "Registrar servicio")
        inicio = self.client.get(reverse("core:inicio"))
        self.assertContains(inicio, "✓ Hecho")
        self.assertEqual(Cliente.objects.count(), 1)

    def test_dos_formularios_y_doble_click_solo_crean_una_visita(self):
        uno = self.payload(self.client.get(self.url))
        dos = self.payload(self.client.get(self.url))
        response = self.client.post(self.url, uno)
        self.assertEqual(self.client.post(self.url, uno).url, response.url)
        self.assertEqual(self.client.post(self.url, dos).url, response.url)
        self.assertRedirects(self.client.get(self.url), response.url)
        self.assertEqual(Atencion.objects.count(), 1)
        self.assertEqual(RegistroServicioAgenda.objects.count(), 1)

    def test_precio_invalido_no_completa_ni_guarda(self):
        pagina = self.client.get(self.url)
        response = self.client.post(self.url, self.payload(pagina, precio_cobrado="-1"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["origen_agenda"])
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, Cita.Estado.PENDIENTE)
        self.assertFalse(Atencion.objects.exists())

    def test_google_precarga_titulo_y_fecha_sin_crear_clienta_o_cita(self):
        url = self.google()
        pagina = self.pagina_google(url)
        self.assertContains(pagina, "Usamos el título del evento")
        self.assertEqual(pagina.context["form"].initial["nombre_cliente"], "Rosa López")
        self.assertEqual(pagina.context["form"].initial["fecha"], self.inicio.date())
        self.assertNotIn("servicio", pagina.context["form"].initial)
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(Cita.objects.count(), 1)

    def test_google_guardado_manual_hecho_persiste_y_recurrencia_siguiente_pendiente(self):
        url = self.google()
        pagina = self.pagina_google(url)
        payload = self.payload(pagina, nombre_cliente="Rosa López", telefono="", cliente_id="", precio_cobrado="350")
        with patch("apps.agenda.registro.GoogleCalendar") as adapter:
            response = self.client.post(url, payload)
            adapter.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Atencion.objects.count(), 1)
        self.assertEqual(Cliente.objects.count(), 2)
        self.assertEqual(Cita.objects.count(), 1)
        for vista in ("dia", "semana"):
            with patch("apps.agenda.lectura_google.GoogleCalendar") as adapter:
                adapter.return_value.eventos.return_value = [dict(self.evento_visible), {**self.evento_visible, "id": "recurrente_ocurrencia_siguiente"}]
                agenda = self.client.get(reverse("agenda:listado"), {"vista": vista})
            eventos = [e["evento_google"] for g in agenda.context["grupos"] for e in g["entradas"] if e.get("evento_google")]
            self.assertTrue(eventos[0]["hecho"])
            self.assertFalse(eventos[1]["hecho"])
            self.assertContains(agenda, "✓ Hecho", count=1)
            self.assertContains(agenda, "Ver servicio", count=1)
        self.assertEqual(self.client.post(url, payload).url, response.url)
        self.assertEqual(self.client.get(url).url, response.url)
        self.assertEqual(Atencion.objects.count(), 1)

    def test_google_todo_el_dia_conserva_fecha(self):
        url = self.google()
        self.evento["start"] = {"date": timezone.localdate().isoformat()}
        pagina = self.pagina_google(url)
        self.assertEqual(pagina.context["form"].initial["fecha"], timezone.localdate())

    def test_evento_google_vinculado_a_cita_completa_ambas_vistas_sin_duplicar(self):
        url = self.google()
        VinculoEventoGoogle.objects.create(cita=self.cita, conexion=self.conexion, calendario_id=self.conexion.calendario_id, evento_id=self.evento["id"])
        pagina = self.pagina_google(url)
        self.assertEqual(pagina.context["form"].initial["cliente_id"], self.clienta.pk)
        response = self.client.post(url, self.payload(pagina))
        self.assertEqual(response.status_code, 302)
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, Cita.Estado.COMPLETADA)
        with patch("apps.agenda.lectura_google.GoogleCalendar") as adapter:
            adapter.return_value.eventos.return_value = [{**self.evento_visible, "inicio": self.inicio+timedelta(hours=2), "fin": self.inicio+timedelta(hours=3)}]
            agenda = self.client.get(reverse("agenda:listado"))
        self.assertContains(agenda, "✓ Hecho", count=2)
        self.assertContains(agenda, "Ver servicio", count=2)
        self.assertNotContains(agenda, "Registrar servicio")
        self.assertEqual(self.client.get(self.url).url, response.url)

    def test_cita_cambiada_no_se_completa_con_formulario_viejo(self):
        pagina = self.client.get(self.url)
        Cita.objects.filter(pk=self.cita.pk).update(version=2)
        response = self.client.post(self.url, self.payload(pagina))
        self.assertContains(response, "La cita cambió")
        self.assertFalse(Atencion.objects.exists())

    def test_cita_cancelada_no_ofrece_registro(self):
        self.cita.estado = Cita.Estado.CANCELADA
        self.cita.save(update_fields=["estado"])
        self.assertNotContains(self.client.get(reverse("agenda:listado")), "Registrar servicio")
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "La cita está cancelada")
        self.assertNotContains(pagina, "Guardar servicio")

    def test_no_cambiar_la_persona_de_una_cita_al_registrar_atencion(self):
        otra = Cliente.objects.create(nombre="Otra Persona")
        pagina = self.client.get(self.url)
        response = self.client.post(self.url, self.payload(pagina, cliente_id=otra.pk, nombre_cliente=otra.nombre))
        self.assertContains(response, "clienta de esta cita")
        self.assertFalse(Atencion.objects.exists())

    def test_firma_csrf_y_sesion_se_requieren_para_guardar(self):
        pagina = self.client.get(self.url)
        datos = self.payload(pagina)
        sin_csrf = {k: v for k, v in datos.items() if k != "csrfmiddlewaretoken"}
        self.assertEqual(self.client.post(self.url, sin_csrf).status_code, 403)
        self.assertContains(self.client.post(self.url, {**datos, "origen_agenda": "alterado"}), "formulario de la agenda venció")
        self.assertContains(self.client.post(self.url, {**datos, "origen_agenda": ""}), "formulario de la agenda venció")
        otra = Client()
        otra.force_login(self.actor)
        self.assertEqual(otra.post(self.url, datos).status_code, 403)
        self.assertFalse(Atencion.objects.exists())

    def test_google_calendario_ajeno_o_cambiado_no_registra(self):
        url = self.google()
        with patch("apps.agenda.registro.GoogleCalendar") as adapter:
            response = self.client.get(url_registro_google("ajeno", self.evento["id"]))
            self.assertContains(response, "calendario cambió")
            adapter.assert_not_called()
        pagina = self.pagina_google(url)
        self.conexion.calendario_id = "otro-calendario"
        self.conexion.save(update_fields=["calendario_id"])
        response = self.client.post(url, self.payload(pagina))
        self.assertContains(response, "calendario cambió")
        self.assertFalse(Atencion.objects.exists())

    def test_google_eliminado_o_error_no_permite_guardar(self):
        url = self.google()
        with patch("apps.agenda.registro.GoogleCalendar") as adapter:
            adapter.return_value.obtener_evento.return_value = None
            self.assertContains(self.client.get(url), "eliminó o canceló")
            adapter.return_value.obtener_evento.side_effect = ErrorGoogle("Reconecta Google.")
            response = self.client.get(url)
            self.assertContains(response, "Reconecta Google.")
            self.assertNotContains(response, "Guardar servicio")

    def test_no_reabrir_cita_con_servicio_registrado_por_edicion(self):
        pagina = self.client.get(self.url)
        self.client.post(self.url, self.payload(pagina))
        self.cita.refresh_from_db()
        datos = {"cliente": self.clienta, "servicios": [], "motivo": "Corte", "inicio": self.cita.inicio, "fin": self.cita.fin, "notas": "", "estado": Cita.Estado.PENDIENTE, "version": self.cita.version}
        with self.assertRaises(ValidationError):
            guardar_cita(actor=self.actor, datos=datos, sesion=self.client.session.session_key, cita_id=self.cita.pk)
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, Cita.Estado.COMPLETADA)

    def test_corregir_precio_materiales_conserva_vinculo_y_no_cambia_persona_de_cita(self):
        pagina = self.client.get(self.url)
        self.client.post(self.url, self.payload(pagina))
        atencion = Atencion.objects.get()
        datos = datos_visita(cliente_id=self.clienta.pk, version=atencion.version, precio_cobrado="420", materiales="Fórmula corregida")
        guardar_atencion(actor=self.actor, datos=datos, atencion_id=atencion.pk)
        atencion.refresh_from_db()
        self.assertEqual(atencion.precio_cobrado, Decimal("420"))
        self.assertEqual(atencion.registro_agenda.cita_id, self.cita.pk)
        otra = Cliente.objects.create(nombre="Otra Persona")
        with self.assertRaises(ValidationError):
            guardar_atencion(actor=self.actor, datos=datos_visita(cliente_id=otra.pk, nombre_cliente=otra.nombre, version=atencion.version), atencion_id=atencion.pk)

    def test_auditoria_fallida_revierte_registro_atencion_y_estado(self):
        pagina = self.client.get(self.url)
        original = EventoAuditoria.objects.create
        def fallar(**kwargs):
            if kwargs["operacion"] == "agenda.servicio_registrado":
                raise RuntimeError("Prueba de fallo")
            return original(**kwargs)
        with patch.object(EventoAuditoria.objects, "create", side_effect=fallar), self.assertRaises(RuntimeError):
            self.client.post(self.url, self.payload(pagina))
        self.assertFalse(Atencion.objects.exists())
        self.assertFalse(RegistroServicioAgenda.objects.exists())
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, Cita.Estado.PENDIENTE)


class RegistroAgendaConcurrenteTests(TransactionTestCase):
    def test_dos_envios_simultaneos_de_la_cita_no_duplican_atencion(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from apps.configuracion.models import ConfiguracionSalon
        ConfiguracionSalon.objects.get_or_create(pk=1)
        actor = get_user_model().objects.create_superuser(username="Marisol", password="SoloPruebas123!")
        clienta = Cliente.objects.create(nombre="Ana López", telefono="9991234567")
        inicio = timezone.now()
        cita = Cita.objects.create(cliente=clienta, responsable=actor, inicio=inicio, fin=inicio+timedelta(hours=1), motivo="Corte", hash_operacion="prueba")
        origen = {"tipo": "cita", "cita_id": cita.pk, "version": cita.version, "cliente_id": clienta.pk, "actor": actor.pk}
        barrera = Barrier(2)
        def guardar(_):
            close_old_connections()
            try:
                usuario = get_user_model().objects.get(pk=actor.pk)
                form = AtencionForm(datos_visita(cliente_id=clienta.pk))
                assert form.is_valid(), form.errors
                barrera.wait(timeout=10)
                return guardar_desde_agenda(actor=usuario, datos=form.cleaned_data, origen=origen).pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(guardar, range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(Atencion.objects.count(), 1)
        self.assertEqual(RegistroServicioAgenda.objects.count(), 1)
