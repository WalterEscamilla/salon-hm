from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.agenda.models import Cita, RegistroServicioAgenda
from apps.asistente.models import Borrador, Conversacion
from apps.asistente.openai_service import ErrorAsistente, conversar
from apps.asistente.services import preparar
from apps.asistente.tests import llamada, respuesta
from apps.clientes.models import Cliente
from .models import Atencion
from .tests import datos_visita


@override_settings(OPENAI_API_KEY="solo-para-pruebas")
class AsistenteDentroFormularioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="Marisol", password="SoloParaPruebas123!")

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.actor)
        self.url = reverse("atenciones:nueva")

    def payload(self, pagina=None, **cambios):
        pagina = pagina or self.client.get(self.url)
        datos = dict(pagina.context["form"].initial)
        for campo in ("clave_operacion", "version", "fecha"):
            if campo not in datos:
                datos[campo] = pagina.context["form"][campo].value()
        datos = {k: "" if v is None else v for k, v in datos.items()}
        return {**datos, "accion": "interpretar", "texto_asistente": "Hoy atendí a Ana López, cobré 120 y usé máquina 2.", "origen_agenda": pagina.context["origen_agenda"], "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value, **cambios}

    def interpretar(self, *, conversacion, origen_agenda, **kwargs):
        preparar(conversacion=conversacion, tipo="atencion", entidad_id=None, datos=datos_visita(servicio="Corte", precio_cobrado="120", materiales="Máquina 2"), origen_agenda=origen_agenda)
        return "Completé el formulario."

    def rellenar(self, **cambios):
        with patch("apps.atenciones.views.conversar", side_effect=self.interpretar):
            return self.client.post(self.url, self.payload(**cambios))

    def guardar(self, pagina, **cambios):
        borrador = pagina.context["borrador_asistente"]
        datos = {k: "" if v is None else v for k, v in borrador.datos.items()}
        datos.update(accion="guardar", borrador_asistente=str(borrador.pk), confirmacion=pagina.context["confirmacion"], version_borrador=borrador.version, origen_agenda=pagina.context["origen_agenda"], csrfmiddlewaretoken=self.client.cookies["csrftoken"].value)
        return self.client.post(self.url, {**datos, **cambios})

    def cita(self):
        cliente = Cliente.objects.create(nombre="Ana López", telefono="9991234567")
        inicio = timezone.now()
        cita = Cita.objects.create(cliente=cliente, responsable=self.actor, inicio=inicio, fin=inicio+timezone.timedelta(hours=1), motivo="Corte", hash_operacion="prueba")
        self.url += f"?cita={cita.pk}"
        return cita

    def test_asistente_arriba_formulario_y_descripcion_opcional_al_guardar_manual(self):
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "Completar con IA")
        self.assertContains(pagina, "Datos del servicio")
        self.assertLess(pagina.content.index(b'TU ASISTENTE'), pagina.content.index(b'Datos del servicio'))
        self.assertFalse(pagina.context["asistente_form"].fields["texto_asistente"].required)
        datos = {**datos_visita(cliente_id=""), "accion": "guardar", "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value}
        self.assertEqual(self.client.post(self.url, datos).status_code, 302)
        self.assertEqual(Atencion.objects.count(), 1)

    def test_interpretar_llena_formulario_en_misma_pagina_sin_guardar(self):
        pagina = self.rellenar()
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual(pagina.context["form"].initial["precio_cobrado"], "120")
        self.assertContains(pagina, "Máquina 2")
        self.assertContains(pagina, "Guardar servicio")
        self.assertNotContains(pagina, "Datos que se guardarán")
        self.assertFalse(Atencion.objects.exists())
        self.assertFalse(Cliente.objects.exists())

    def test_correccion_precio_guardado_humano_y_doble_envio(self):
        pagina = self.rellenar()
        response = self.guardar(pagina, precio_cobrado="100")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.guardar(pagina, precio_cobrado="100").url, response.url)
        self.assertEqual(Atencion.objects.get().precio_cobrado, Decimal("100"))
        self.assertEqual(Cliente.objects.count(), 1)

    def test_descripcion_vacia_no_llama_a_openai(self):
        with patch("apps.atenciones.views.conversar") as api:
            pagina = self.client.post(self.url, self.payload(texto_asistente=""))
        api.assert_not_called()
        self.assertContains(pagina, "Describe el servicio")

    def test_error_externo_conserva_datos_escritos_para_guardado_manual(self):
        with patch("apps.atenciones.views.conversar", side_effect=ErrorAsistente("No pudimos conectar.")):
            pagina = self.client.post(self.url, self.payload(nombre_cliente="Ana", precio_cobrado="115", materiales="Tijeras", servicio="Corte"))
        self.assertContains(pagina, "No pudimos conectar.")
        self.assertEqual(pagina.context["form"].initial["precio_cobrado"], "115")
        self.assertEqual(pagina.context["form"].initial["materiales"], "Tijeras")
        self.assertFalse(Atencion.objects.exists())

    def test_avisos_arriba_si_faltan_datos_obligatorios(self):
        def incompleto(**kwargs):
            preparar(conversacion=kwargs["conversacion"], tipo="atencion", entidad_id=None, datos=datos_visita(nombre_cliente="", fecha=None, servicio="Corte", precio_cobrado=None), avisos=["Tono por confirmar."], permitir_incompleto=True)
            return "Formulario listo."
        with patch("apps.atenciones.views.conversar", side_effect=incompleto):
            pagina = self.client.post(self.url, self.payload())
        self.assertContains(pagina, "Falta el nombre")
        self.assertContains(pagina, "Falta la fecha")
        self.assertContains(pagina, "Tono por confirmar")
        self.assertIsNone(pagina.context["form"].initial["precio_cobrado"])

    def test_agenda_interpretar_no_completa_y_guardar_mantiene_vinculo(self):
        cita = self.cita()
        pagina = self.rellenar()
        borrador = pagina.context["borrador_asistente"]
        self.assertEqual(borrador.origen_agenda["cita_id"], cita.pk)
        self.assertContains(pagina, "está vinculado al evento")
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "pendiente")
        self.assertFalse(RegistroServicioAgenda.objects.exists())
        response = self.guardar(pagina, precio_cobrado="95")
        self.assertEqual(response.status_code, 302)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "completada")
        self.assertEqual(RegistroServicioAgenda.objects.get().atencion.precio_cobrado, Decimal("95"))

    def test_recargar_y_abrir_en_seccion_asistente_conservan_vinculo_de_agenda(self):
        cita = self.cita()
        pagina = self.rellenar()
        borrador = pagina.context["borrador_asistente"]
        recarga = self.client.get(reverse("atenciones:nueva"), {"borrador": str(borrador.pk)})
        self.assertEqual(recarga.context["form"].initial["materiales"], "Máquina 2")
        self.assertTrue(recarga.context["origen_agenda"])
        url = reverse("asistente:borrador", args=[borrador.pk])
        pagina = self.client.get(url)
        self.assertContains(pagina, "vinculado a un evento")
        datos = {**borrador.datos, "cliente_id": borrador.datos["cliente_id"] or "", "accion": "guardar", "version_borrador": borrador.version, "confirmacion": pagina.context["confirmacion"], "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value}
        self.assertEqual(self.client.post(url, datos).status_code, 302)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "completada")

    def test_reinterpretar_sustituye_borrador_y_conserva_correciones_del_formulario(self):
        pagina = self.rellenar()
        anterior = pagina.context["borrador_asistente"]
        payload = self.payload(pagina, borrador_asistente=str(anterior.pk), precio_cobrado="90", texto_asistente="Corrige: también usé tijeras")
        with patch("apps.atenciones.views.conversar", side_effect=self.interpretar) as api:
            nueva = self.client.post(self.url, payload)
        self.assertEqual(api.call_args.kwargs["formulario"]["precio_cobrado"], "90")
        anterior.refresh_from_db()
        self.assertEqual(anterior.estado, "descartado")
        self.assertNotEqual(nueva.context["borrador_asistente"].pk, anterior.pk)

    def test_respuesta_parcial_para_rellenar_sin_navegar(self):
        with patch("apps.atenciones.views.conversar", side_effect=self.interpretar):
            pagina = self.client.post(self.url, self.payload(), HTTP_HX_REQUEST="true", HTTP_HX_TARGET="registro-servicio")
        self.assertContains(pagina, 'id="registro-servicio"')
        self.assertNotContains(pagina, "<!doctype")
        self.assertContains(pagina, "Máquina 2")

    def test_csrf_y_permisos_para_asistente_en_formulario(self):
        datos = self.payload()
        datos.pop("csrfmiddlewaretoken")
        self.assertEqual(self.client.post(self.url, datos).status_code, 403)
        from django.contrib.auth.models import Permission
        usuario = get_user_model().objects.create_user(username="manual", password="SoloParaPruebas123!")
        usuario.user_permissions.add(*Permission.objects.filter(codename__in=["add_atencion", "view_cliente"]))
        self.client.force_login(usuario)
        pagina = self.client.get(self.url)
        self.assertNotContains(pagina, "Completar con IA")
        self.assertEqual(self.client.post(self.url, self.payload(pagina)).status_code, 403)

    def test_borrador_ajeno_o_de_otra_sesion_no_rellena_formulario(self):
        pagina = self.rellenar()
        borrador = pagina.context["borrador_asistente"]
        otro = Client()
        otro.force_login(self.actor)
        self.assertEqual(otro.get(self.url, {"borrador": str(borrador.pk)}).status_code, 404)

    def test_precio_invalido_despues_de_interpretar_no_guarda_y_conserva_datos(self):
        pagina = self.rellenar()
        response = self.guardar(pagina, precio_cobrado="-1", materiales="Corrección para conservar")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Corrección para conservar")
        self.assertContains(response, "Completar con IA")
        self.assertFalse(Atencion.objects.exists())

    def test_contexto_fecha_es_serializable_y_modo_restringe_herramientas(self):
        self.client.get(self.url)
        conv = Conversacion.objects.create(usuario=self.actor, sesion=self.client.session.session_key)
        args = {k: v for k, v in datos_visita(servicio="Corte", precio_cobrado="120").items() if k not in ("version", "clave_operacion")}
        args["avisos"] = []
        api = MagicMock()
        api.responses.create.side_effect = [llamada("preparar_atencion", args)]
        with patch("apps.atenciones.views.conversar", side_effect=lambda **kwargs: conversar(**kwargs, cliente_api=api)):
            pagina = self.client.post(self.url, self.payload())
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual(api.responses.create.call_count, 1)
        self.assertEqual({tool["name"] for tool in api.responses.create.call_args.kwargs["tools"]}, {"buscar_clientas", "preparar_atencion"})
        self.assertFalse(Atencion.objects.exists())
