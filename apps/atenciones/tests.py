from datetime import timedelta
from decimal import Decimal
import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.auditoria.models import EventoAuditoria
from apps.clientes.models import Cliente
from apps.clientes.services import guardar_cliente
from apps.inventario.models import MovimientoStock
from apps.asistente.models import Borrador, Conversacion
from apps.asistente.openai_service import conversar, ejecutar_herramienta
from apps.asistente.services import confirmar, editar_borrador, preparar, token_confirmacion
from apps.asistente.tests import llamada, respuesta
from .models import Atencion
from .services import ClientaAmbigua, guardar_atencion


def datos_visita(**extra):
    return {"nombre_cliente": "Ana López", "telefono": "9991234567", "cliente_id": None, "crear_nueva": False, "fecha": timezone.localdate().isoformat(), "servicio": "Retoque de raíz y corte", "precio_cobrado": "500", "materiales": "Tinte 6.0 y peróxido de 20 volúmenes, cantidades no medidas", "notas": "Prefiere conservar el largo", "clave_operacion": str(uuid.uuid4()), "version": 1, **extra}


class AtencionesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="Marisol", password="ClaveParaPruebas123!")

    def guardar(self, datos=None, **extra):
        return guardar_atencion(actor=self.actor, datos=datos or datos_visita(), **extra)

    def clienta(self, **extra):
        return guardar_cliente(actor=self.actor, datos={"nombre": "Ana López", "telefono": "9991234567", "notas": "", **extra})

    def test_crear_clienta_y_visita_en_un_solo_registro(self):
        atencion = self.guardar()
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(atencion.cliente.nombre, "Ana López")
        self.assertEqual(atencion.precio_cobrado, Decimal("500"))
        self.assertIn("cantidades no medidas", atencion.materiales)
        self.assertFalse(MovimientoStock.objects.exists())

    def test_reconocer_nombre_sin_acentos_y_telefono_mexicano(self):
        cliente = self.clienta()
        atencion = self.guardar(datos_visita(nombre_cliente="ana lopez", telefono="+52 999 123 4567"))
        self.assertEqual(atencion.cliente_id, cliente.pk)
        self.assertEqual(Cliente.objects.count(), 1)

    def test_precios_preferenciales_se_conservan_por_visita(self):
        uno = self.guardar(datos_visita(precio_cobrado="500"))
        dos = self.guardar(datos_visita(precio_cobrado="420", fecha=(timezone.localdate() - timedelta(days=1)).isoformat()))
        uno.refresh_from_db()
        self.assertEqual(uno.precio_cobrado, Decimal("500"))
        self.assertEqual(dos.precio_cobrado, Decimal("420"))
        self.assertEqual(uno.cliente_id, dos.cliente_id)

    def test_precio_desconocido_y_cero_se_distinguen(self):
        desconocido = self.guardar(datos_visita(precio_cobrado=""))
        gratis = self.guardar(datos_visita(precio_cobrado="0"))
        self.assertIsNone(desconocido.precio_cobrado)
        self.assertEqual(gratis.precio_cobrado, Decimal("0"))

    def test_homonimos_requieren_eleccion_y_telefono_distingue(self):
        una = self.clienta()
        otra = self.clienta(telefono="9998887777")
        with self.assertRaises(ClientaAmbigua):
            self.guardar(datos_visita(telefono=""))
        atencion = self.guardar(datos_visita(telefono="9998887777"))
        self.assertEqual(atencion.cliente_id, otra.pk)
        elegida = self.guardar(datos_visita(cliente_id=una.pk, telefono=""))
        self.assertEqual(elegida.cliente_id, una.pk)

    def test_nombre_parcial_o_telefono_distinto_no_fusionan_personas(self):
        self.clienta()
        for cambios in ({"nombre_cliente": "Ana", "telefono": ""}, {"telefono": "9990000000"}, {"nombre_cliente": "Otra Persona"}):
            with self.assertRaises(ClientaAmbigua):
                self.guardar(datos_visita(**cambios))
        self.assertFalse(Atencion.objects.exists())

    def test_nueva_persona_homonima_permite_crear_y_no_duplica_identidad_exacta(self):
        self.clienta()
        atencion = self.guardar(datos_visita(telefono="9990000000", crear_nueva=True))
        self.assertEqual(Cliente.objects.count(), 2)
        self.assertEqual(atencion.cliente.telefono, "9990000000")
        with self.assertRaises(ValidationError):
            self.guardar(datos_visita(crear_nueva=True))

    def test_completar_telefono_vacio_sin_sobrescribir_otro(self):
        cliente = self.clienta(telefono="")
        self.guardar()
        cliente.refresh_from_db()
        self.assertEqual(cliente.telefono, "9991234567")
        self.guardar(datos_visita(cliente_id=cliente.pk, telefono="9990000000"))
        cliente.refresh_from_db()
        self.assertEqual(cliente.telefono, "9991234567")

    def test_doble_click_no_duplica_clienta_ni_visita(self):
        datos = datos_visita()
        self.assertEqual(self.guardar(datos).pk, self.guardar(datos).pk)
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(Atencion.objects.count(), 1)
        with self.assertRaises(ValidationError):
            self.guardar({**datos, "precio_cobrado": "999"})

    def test_negativos_futuros_y_servicio_vacio_no_crean_clientas(self):
        for cambios in ({"precio_cobrado": "-1"}, {"servicio": ""}, {"fecha": (timezone.localdate() + timedelta(days=1)).isoformat()}):
            with self.assertRaises(ValidationError):
                self.guardar(datos_visita(**cambios))
        self.assertFalse(Cliente.objects.exists())

    def test_permisos_y_rollback_creacion_clienta_con_visita(self):
        sin_permiso = get_user_model().objects.create_user(username="sinpermiso")
        with self.assertRaises(PermissionDenied):
            guardar_atencion(actor=sin_permiso, datos=datos_visita())
        original = EventoAuditoria.objects.create
        def fallar(**kwargs):
            if kwargs["operacion"] == "atencion.creada":
                raise RuntimeError("Prueba")
            return original(**kwargs)
        with patch.object(EventoAuditoria.objects, "create", side_effect=fallar):
            with self.assertRaises(RuntimeError):
                self.guardar()
        self.assertFalse(Cliente.objects.exists())
        self.assertFalse(Atencion.objects.exists())

    def test_editar_registro_controla_version(self):
        atencion = self.guardar()
        datos = datos_visita(cliente_id=atencion.cliente_id, precio_cobrado="450", version=atencion.version)
        self.guardar(datos, atencion_id=atencion.pk)
        with self.assertRaises(ValidationError):
            self.guardar(datos, atencion_id=atencion.pk)
        atencion.refresh_from_db()
        self.assertEqual(atencion.precio_cobrado, Decimal("450"))

    def test_historial_prioriza_fecha_real_y_muestra_materiales(self):
        reciente = self.guardar()
        self.guardar(datos_visita(fecha=(timezone.localdate() - timedelta(days=30)).isoformat(), servicio="Corte anterior"))
        self.client.force_login(self.actor)
        response = self.client.get(reverse("clientes:detalle", args=[reciente.cliente_id]))
        self.assertEqual(response.context["ultima"].pk, reciente.pk)
        self.assertContains(response, "Tinte 6.0")
        self.assertContains(response, "Corte anterior")

    def test_formulario_privado_csrf_y_guardado_humano(self):
        navegador = Client(enforce_csrf_checks=True)
        self.assertEqual(navegador.get(reverse("atenciones:nueva")).status_code, 302)
        navegador.force_login(self.actor)
        pagina = navegador.get(reverse("atenciones:nueva"))
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual(navegador.post(reverse("atenciones:nueva"), datos_visita(cliente_id="")).status_code, 403)
        datos = datos_visita()
        datos.pop("cliente_id")
        response = navegador.post(reverse("atenciones:nueva"), {**datos, "csrfmiddlewaretoken": navegador.cookies["csrftoken"].value})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Atencion.objects.count(), 1)


class AsistenteAtencionesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="Marisol", password="ClaveParaPruebas123!")

    def setUp(self):
        self.conv = Conversacion.objects.create(usuario=self.actor, sesion="sesion-visitas")

    def borrador(self, **extra):
        return preparar(conversacion=self.conv, tipo="atencion", entidad_id=None, datos=datos_visita(**extra))

    def confirmar(self, borrador):
        return confirmar(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, token=token_confirmacion(borrador))

    def test_cliente_y_atencion_solo_se_crean_al_confirmar(self):
        borrador = self.borrador()
        self.assertFalse(Cliente.objects.exists())
        self.assertFalse(Atencion.objects.exists())
        uno = self.confirmar(borrador)
        dos = self.confirmar(borrador)
        self.assertEqual(uno, dos)
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(Atencion.objects.count(), 1)
        self.assertFalse(MovimientoStock.objects.exists())

    def test_edicion_borrador_precio_materiales_invalida_confirmacion_anterior(self):
        borrador = self.borrador()
        token = token_confirmacion(borrador)
        editar_borrador(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, datos=datos_visita(precio_cobrado="420", materiales="Tinte 7.0"), version=1)
        with self.assertRaises(ValidationError):
            confirmar(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, token=token)
        borrador.refresh_from_db()
        self.confirmar(borrador)
        self.assertEqual(Atencion.objects.get().precio_cobrado, Decimal("420"))
        self.assertEqual(Atencion.objects.get().materiales, "Tinte 7.0")

    def test_clienta_creada_despues_del_borrador_no_se_duplica(self):
        borrador = self.borrador()
        guardar_cliente(actor=self.actor, datos={"nombre": "Ana López", "telefono": "9991234567", "notas": ""})
        with self.assertRaises(ValidationError):
            self.confirmar(borrador)
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertFalse(Atencion.objects.exists())

    def test_no_seleccionar_id_sin_consultar_y_ambiguedad_prepara_formulario(self):
        for numero in ("9991234567", "9990000000"):
            guardar_cliente(actor=self.actor, datos={"nombre": "Ana López", "telefono": numero, "notas": ""})
        args = {k: v for k, v in datos_visita(telefono="", precio_cobrado=None).items() if k not in ("clave_operacion", "version")}
        args["avisos"] = []
        resultado = ejecutar_herramienta(conversacion=self.conv, nombre="preparar_atencion", args=args, observados=set())
        self.assertIsNone(resultado["datos"]["cliente_id"])
        self.assertEqual(Borrador.objects.count(), 1)
        self.assertFalse(Atencion.objects.exists())
        args["cliente_id"] = Cliente.objects.first().pk
        with self.assertRaises(ValidationError):
            ejecutar_herramienta(conversacion=self.conv, nombre="preparar_atencion", args=args, observados=set())

    def test_tool_loop_natural_prepara_visita_sin_duracion_ni_cantidades(self):
        args = {k: v for k, v in datos_visita().items() if k not in ("clave_operacion", "version")}
        args["avisos"] = []
        api = MagicMock()
        api.responses.create.side_effect = [
            llamada("buscar_clientas", {"nombre": "Ana López", "telefono": "9991234567", "id": None}),
            llamada("preparar_atencion", args, call_id="call_2"),
            respuesta("Propuesta de visita preparada para confirmar."),
        ]
        conversar(conversacion=self.conv, texto="Hoy atendí a Ana López, cobré 500 y usé tinte 6.0 con peróxido.", cliente_api=api)
        self.assertEqual(Borrador.objects.get().tipo, "atencion")
        self.assertFalse(Atencion.objects.exists())
        self.assertFalse(Cliente.objects.exists())

    def test_consultar_ultima_visita_sin_escribir(self):
        atencion = guardar_atencion(actor=self.actor, datos=datos_visita())
        vistos = set()
        ejecutar_herramienta(conversacion=self.conv, nombre="buscar_clientas", args={"nombre": "Ana Lopez", "telefono": "", "id": None}, observados=vistos)
        resultado = ejecutar_herramienta(conversacion=self.conv, nombre="consultar_historial", args={"cliente_id": atencion.cliente_id}, observados=vistos)
        self.assertEqual(resultado["visitas"][0]["materiales"], atencion.materiales)
        self.assertEqual(resultado["visitas"][0]["precio_cobrado"], "500.00")
        self.assertFalse(Borrador.objects.exists())

    def test_confirmacion_http_servicio_realizado_y_clienta_nueva(self):
        navegador = Client(enforce_csrf_checks=True)
        navegador.force_login(self.actor)
        navegador.get(reverse("asistente:chat"))
        conv = Conversacion.objects.get(usuario=self.actor, sesion=navegador.session.session_key)
        borrador = preparar(conversacion=conv, tipo="atencion", entidad_id=None, datos=datos_visita())
        url = reverse("asistente:borrador", args=[borrador.pk])
        pagina = navegador.get(url)
        self.assertContains(pagina, "se creará al guardar")
        datos = {"accion": "confirmar", "confirmacion": pagina.context["confirmacion"]}
        self.assertEqual(navegador.post(url, datos).status_code, 403)
        response = navegador.post(url, {**datos, "csrfmiddlewaretoken": navegador.cookies["csrftoken"].value})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(Atencion.objects.count(), 1)
        self.assertContains(navegador.get(response.url), "Tinte 6.0")


class AtencionesConcurrentesTests(TransactionTestCase):
    def test_envios_simultaneos_misma_operacion_no_duplican_clienta(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from apps.configuracion.models import ConfiguracionSalon
        ConfiguracionSalon.objects.get_or_create(pk=1)
        actor = get_user_model().objects.create_superuser(username="Marisol", password="ClaveParaPruebas123!")
        datos = datos_visita()
        barrera = Barrier(2)

        def ejecutar(_):
            close_old_connections()
            try:
                usuario = get_user_model().objects.get(pk=actor.pk)
                barrera.wait(timeout=10)
                return guardar_atencion(actor=usuario, datos=datos).pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(ejecutar, range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(Atencion.objects.count(), 1)
