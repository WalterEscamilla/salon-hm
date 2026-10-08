from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.atenciones.models import Atencion
from apps.atenciones.tests import datos_herramienta_visita, datos_visita
from apps.auditoria.models import EventoAuditoria
from apps.clientes.models import Cliente
from apps.clientes.services import guardar_cliente
from apps.inventario.models import MovimientoStock
from .models import Borrador, Conversacion
from .openai_service import ejecutar_herramienta
from .services import editar_borrador, guardar_formulario_atencion, preparar, token_confirmacion
from .tests import datos_servicio


class FormularioAtencionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="Marisol", password="ClaveParaPruebas123!")

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.actor)
        self.client.get(reverse("asistente:chat"))
        self.conv = Conversacion.objects.get(usuario=self.actor, sesion=self.client.session.session_key)

    def preparar(self, **datos):
        return preparar(conversacion=self.conv, tipo="atencion", entidad_id=None, datos=datos_visita(**datos))

    def herramienta(self, **datos):
        args = datos_herramienta_visita(**datos)
        args.setdefault("avisos", [])
        resultado = ejecutar_herramienta(conversacion=self.conv, nombre="preparar_atencion", args=args, observados=set())
        return Borrador.objects.get(pk=resultado["borrador_id"])

    def payload(self, borrador, **cambios):
        pagina = self.client.get(reverse("asistente:borrador", args=[borrador.pk]))
        datos = {k: "" if v is None else v for k, v in borrador.datos.items()}
        return {**datos, "accion": "guardar", "confirmacion": pagina.context["confirmacion"], "version_borrador": borrador.version, "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value, **cambios}

    def guardar(self, borrador, **cambios):
        return self.client.post(reverse("asistente:borrador", args=[borrador.pk]), self.payload(borrador, **cambios))

    def clienta(self, **cambios):
        return guardar_cliente(actor=self.actor, datos={"nombre": "Ana López", "telefono": "9991234567", "notas": "", **cambios})

    def test_chat_abre_solo_el_formulario_nuevo_y_no_un_pendiente_anterior(self):
        antiguo = self.preparar(nombre_cliente="Otra Persona", telefono="")
        creados = []
        def interpretar(**kwargs):
            nuevo = self.preparar()
            creados.append(nuevo)
            return "Formulario preparado."
        with patch("apps.asistente.views.conversar", side_effect=interpretar):
            response = self.client.post(reverse("asistente:chat"), {"texto": "Hoy atendí a Ana", "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value})
        self.assertRedirects(response, reverse("asistente:borrador", args=[creados[0].pk]))
        antiguo.refresh_from_db()
        self.assertEqual(antiguo.estado, "pendiente")
        self.assertFalse(Atencion.objects.exists())

    def test_consulta_de_historial_no_redirige_a_formulario_anterior(self):
        self.preparar()
        with patch("apps.asistente.views.conversar", return_value="Su última visita fue un corte."):
            response = self.client.post(reverse("asistente:chat"), {"texto": "¿Qué le hice a Ana?", "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value})
        self.assertRedirects(response, reverse("asistente:chat"))

    def test_varias_visitas_permanecen_accesibles_en_chat(self):
        def interpretar(**kwargs):
            self.preparar()
            self.preparar(nombre_cliente="Otra Persona", telefono="")
        with patch("apps.asistente.views.conversar", side_effect=interpretar):
            response = self.client.post(reverse("asistente:chat"), {"texto": "Atendí a dos clientas", "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value})
        self.assertRedirects(response, reverse("asistente:chat"))

    def test_formulario_precargado_sin_resumen_ni_segunda_confirmacion(self):
        borrador = self.preparar()
        response = self.client.get(reverse("asistente:borrador", args=[borrador.pk]))
        self.assertContains(response, 'value="Ana López"')
        self.assertContains(response, "Guardar servicio")
        self.assertNotContains(response, "Datos que se guardarán")
        self.assertNotContains(response, "Modificar la propuesta")
        self.assertNotContains(response, "Confirmar y guardar")
        self.assertNotContains(response, "Hay datos por aclarar")

    def test_guardar_correcciones_en_un_paso_y_doble_envio_no_duplica(self):
        borrador = self.preparar()
        datos = self.payload(borrador, precio_cobrado="420", materiales="Tinte 7.0", nombre_cliente="Ana Gómez", clave_operacion=str(uuid.uuid4()))
        url = reverse("asistente:borrador", args=[borrador.pk])
        response = self.client.post(url, datos)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.post(url, datos).url, response.url)
        atencion = Atencion.objects.get()
        self.assertEqual(atencion.precio_cobrado, Decimal("420"))
        self.assertEqual(atencion.materiales, "Tinte 7.0")
        self.assertEqual(atencion.cliente.nombre, "Ana Gómez")
        self.assertEqual(str(atencion.clave_operacion), borrador.datos["clave_operacion"])
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertFalse(MovimientoStock.objects.exists())
        borrador.refresh_from_db()
        self.assertEqual(borrador.estado, "confirmado")
        self.assertEqual(borrador.datos["nombre_cliente"], "Ana López")
        self.assertEqual(EventoAuditoria.objects.get(operacion="borrador.confirmado").cambios["aprobacion"], "formulario")

    def test_datos_faltantes_y_dudas_arriba_sin_inventar_fecha_ni_precio(self):
        borrador = self.herramienta(nombre_cliente=None, telefono=None, servicio=None, fecha=None, precio_cobrado=None, avisos=["No está claro qué tono se utilizó."])
        pagina = self.client.get(reverse("asistente:borrador", args=[borrador.pk]))
        self.assertContains(pagina, "No está claro qué tono se utilizó.")
        self.assertContains(pagina, "Falta el nombre")
        self.assertContains(pagina, "Falta precisar")
        self.assertContains(pagina, "Falta la fecha")
        self.assertIsNone(pagina.context["form"].initial["fecha"])
        self.assertIsNone(borrador.datos["precio_cobrado"])
        self.assertLess(pagina.content.index(b'Hay datos por aclarar'), pagina.content.index(b'<form method="post">'))
        response = self.guardar(borrador)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Atencion.objects.exists())
        response = self.guardar(borrador, nombre_cliente="Ana López", fecha=timezone.localdate().isoformat(), servicio="Corte")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(Atencion.objects.get().precio_cobrado)

    def test_homonimos_se_eligen_en_formulario_sin_crear_otra_persona(self):
        self.clienta()
        otra = self.clienta(telefono="9998887777")
        borrador = self.herramienta(telefono="")
        pagina = self.client.get(reverse("asistente:borrador", args=[borrador.pk]))
        self.assertEqual(len(pagina.context["coincidencias"]), 2)
        self.assertContains(pagina, "Hay posibles coincidencias")
        self.assertEqual(self.guardar(borrador).status_code, 200)
        self.assertFalse(Atencion.objects.exists())
        response = self.guardar(borrador, cliente_id=otra.pk)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Atencion.objects.get().cliente_id, otra.pk)
        self.assertEqual(Cliente.objects.count(), 2)

    def test_clienta_existente_correccion_no_duplica_y_respeta_precio_variable(self):
        clienta = self.clienta()
        borrador = self.preparar()
        response = self.guardar(borrador, precio_cobrado="0", notas="Promoción de hoy")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Atencion.objects.get().cliente_id, clienta.pk)
        self.assertEqual(Atencion.objects.get().precio_cobrado, Decimal("0"))
        self.assertEqual(Cliente.objects.count(), 1)

    def test_no_guardar_si_identidad_original_cambio_despues_de_interpretar(self):
        borrador = self.preparar()
        self.clienta()
        response = self.guardar(borrador, precio_cobrado="450")
        self.assertContains(response, "Los datos de la clienta cambiaron")
        self.assertFalse(Atencion.objects.exists())
        self.assertEqual(Cliente.objects.count(), 1)

    def test_precio_invalido_conserva_formulario_y_no_escribe(self):
        borrador = self.preparar()
        response = self.guardar(borrador, precio_cobrado="-1", materiales="Corrección que quiero conservar")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Corrección que quiero conservar")
        self.assertIn("precio_cobrado", response.context["form"].errors)
        self.assertFalse(Cliente.objects.exists())

    def test_csrf_y_token_obligatorios(self):
        borrador = self.preparar()
        datos = self.payload(borrador)
        datos.pop("csrfmiddlewaretoken")
        url = reverse("asistente:borrador", args=[borrador.pk])
        self.assertEqual(self.client.post(url, datos).status_code, 403)
        self.assertEqual(self.guardar(borrador, confirmacion="alterado").status_code, 200)
        self.assertFalse(Atencion.objects.exists())

    def test_token_anterior_no_guarda_despues_de_edicion_en_otra_ventana(self):
        borrador = self.preparar()
        datos = self.payload(borrador)
        editar_borrador(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, datos=datos_visita(precio_cobrado="600"), version=1)
        response = self.client.post(reverse("asistente:borrador", args=[borrador.pk]), datos)
        self.assertContains(response, "cambió en otra ventana")
        self.assertFalse(Atencion.objects.exists())

    def test_formulario_de_otra_sesion_no_es_accesible(self):
        borrador = self.preparar()
        otra_sesion = Client()
        otra_sesion.force_login(self.actor)
        self.assertEqual(otra_sesion.get(reverse("asistente:borrador", args=[borrador.pk])).status_code, 404)
        with self.assertRaises(PermissionDenied):
            guardar_formulario_atencion(borrador_id=borrador.pk, actor=self.actor, sesion="otra", token=token_confirmacion(borrador), datos=datos_visita(), version=1)

    def test_vencido_o_descartado_no_guarda(self):
        borrador = self.preparar()
        for cambios in ({"vence": timezone.now() - timedelta(seconds=1)}, {"estado": "descartado", "vence": timezone.now() + timedelta(minutes=5)}):
            Borrador.objects.filter(pk=borrador.pk).update(**cambios)
            response = self.guardar(borrador)
            self.assertContains(response, "venció o se descartó")
        self.assertFalse(Atencion.objects.exists())

    def test_auditoria_fallida_revierte_clienta_visita_y_estado(self):
        borrador = self.preparar()
        original = EventoAuditoria.objects.create
        def fallar(**kwargs):
            if kwargs["operacion"] == "borrador.confirmado":
                raise RuntimeError("Fallo simulado de auditoría")
            return original(**kwargs)
        with patch.object(EventoAuditoria.objects, "create", side_effect=fallar), self.assertRaises(RuntimeError):
            self.guardar(borrador)
        self.assertFalse(Cliente.objects.exists())
        self.assertFalse(Atencion.objects.exists())
        borrador.refresh_from_db()
        self.assertEqual(borrador.estado, "pendiente")

    def test_catalogo_conserva_resumen_y_confirmacion(self):
        borrador = preparar(conversacion=self.conv, tipo="servicio", entidad_id=None, datos=datos_servicio())
        pagina = self.client.get(reverse("asistente:borrador", args=[borrador.pk]))
        self.assertContains(pagina, "Datos que se guardarán")
        self.assertContains(pagina, "Confirmar y guardar")

    def test_avisos_rechazan_tipos_y_tamanos_invalidos(self):
        for avisos in ([123], ["a"] * 9, ["a" * 501]):
            with self.assertRaises(ValidationError):
                self.herramienta(avisos=avisos)
        self.assertFalse(Borrador.objects.exists())
