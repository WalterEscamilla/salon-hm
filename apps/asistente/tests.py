from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from openai import AuthenticationError, APIConnectionError
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.auditoria.models import EventoAuditoria
from apps.catalogos.models import Servicio
from apps.inventario.models import MovimientoStock, Producto
from apps.inventario.services import guardar_producto, registrar_movimiento
from apps.inventario.tests import datos_movimiento, datos_producto
from .models import Borrador, Conversacion, Mensaje
from .openai_service import ErrorAsistente, TOOLS, conversar, ejecutar_herramienta
from .services import confirmar, editar_borrador, preparar, token_confirmacion


def datos_servicio(**extra):
    return {"nombre": "Corte", "descripcion": "", "duracion_minutos": 45, "precio_base": "250.00", "activo": True, **extra}


def llamada(nombre, args, call_id="call_1"):
    item = SimpleNamespace(type="function_call", name=nombre, arguments=json.dumps(args), call_id=call_id)
    item.model_dump = lambda **kwargs: {"type": "function_call", "name": nombre, "arguments": item.arguments, "call_id": call_id, "id": "fc_1"}
    return SimpleNamespace(output=[item], output_text="")


def respuesta(texto):
    return SimpleNamespace(output=[], output_text=texto)


class AsistenteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="Marisol", password="ClaveParaPruebas123!")

    def setUp(self):
        self.conv = Conversacion.objects.create(usuario=self.actor, sesion="sesion-1")

    def preparar_servicio(self, **extra):
        return preparar(conversacion=self.conv, tipo="servicio", entidad_id=None, datos=datos_servicio(**extra))

    def confirmar(self, borrador, **extra):
        return confirmar(borrador_id=borrador.pk, actor=self.actor, sesion="sesion-1", token=token_confirmacion(borrador), **extra)

    def test_preparacion_no_escribe_catalogo_y_doble_confirmacion_no_duplica(self):
        borrador = self.preparar_servicio()
        self.assertFalse(Servicio.objects.exists())
        self.assertEqual(self.confirmar(borrador), self.confirmar(borrador))
        self.assertEqual(Servicio.objects.count(), 1)
        self.assertEqual(EventoAuditoria.objects.filter(operacion="borrador.confirmado").count(), 1)

    def test_confirmacion_vinculada_a_usuario_sesion_y_datos_exactos(self):
        borrador = self.preparar_servicio()
        token = token_confirmacion(borrador)
        with self.assertRaises(PermissionDenied):
            confirmar(borrador_id=borrador.pk, actor=self.actor, sesion="otra-sesion", token=token)
        otra = get_user_model().objects.create_superuser(username="Otra", password="ClaveParaPruebas123!")
        with self.assertRaises(PermissionDenied):
            confirmar(borrador_id=borrador.pk, actor=otra, sesion="sesion-1", token=token)
        editar_borrador(borrador_id=borrador.pk, actor=self.actor, sesion="sesion-1", datos=datos_servicio(precio_base="300"), version=1)
        with self.assertRaises(ValidationError):
            confirmar(borrador_id=borrador.pk, actor=self.actor, sesion="sesion-1", token=token)
        self.assertFalse(Servicio.objects.exists())
        borrador.refresh_from_db()
        self.confirmar(borrador)
        self.assertEqual(str(Servicio.objects.get().precio_base), "300.00")

    def test_borrador_vencido_y_descartado_no_guardan(self):
        borrador = self.preparar_servicio()
        for cambios in ({"vence": timezone.now() - timedelta(minutes=1)}, {"estado": "descartado", "vence": timezone.now() + timedelta(minutes=10)}):
            Borrador.objects.filter(pk=borrador.pk).update(**cambios)
            borrador.refresh_from_db()
            with self.assertRaises(ValidationError):
                self.confirmar(borrador)
        self.assertFalse(Servicio.objects.exists())

    def test_catalogo_cambiado_no_sobrescribe_nuevos_datos(self):
        servicio = Servicio.objects.create(**datos_servicio())
        borrador = preparar(conversacion=self.conv, tipo="servicio", entidad_id=servicio.pk, datos=datos_servicio(precio_base="280"))
        Servicio.objects.filter(pk=servicio.pk).update(precio_base="310")
        with self.assertRaises(ValidationError):
            self.confirmar(borrador)
        servicio.refresh_from_db()
        self.assertEqual(str(servicio.precio_base), "310.00")

    def test_crear_producto_y_stock_dos_confirmaciones(self):
        borrador = preparar(conversacion=self.conv, tipo="producto", entidad_id=None, datos=datos_producto(costo_envase=None))
        self.assertFalse(Producto.objects.exists())
        self.confirmar(borrador)
        producto = Producto.objects.get()
        borrador_stock = preparar(conversacion=self.conv, tipo="stock", entidad_id=producto.pk, datos={"tipo": "entrada", "cantidad": "1000", "unidad": "ml", "motivo": "Existencias iniciales"})
        self.assertFalse(MovimientoStock.objects.exists())
        self.confirmar(borrador_stock)
        self.confirmar(borrador_stock)
        producto.refresh_from_db()
        self.assertEqual(producto.existencias, 1000)
        self.assertEqual(MovimientoStock.objects.count(), 1)
        self.assertIsNone(MovimientoStock.objects.get().costo_por_unidad)

    def test_stock_cambiado_desde_revision_exige_nuevo_borrador(self):
        producto = guardar_producto(actor=self.actor, datos=datos_producto())
        borrador = preparar(conversacion=self.conv, tipo="stock", entidad_id=producto.pk, datos={"tipo": "entrada", "cantidad": "1000", "unidad": "ml", "motivo": "Compra"})
        registrar_movimiento(actor=self.actor, producto_id=producto.pk, datos=datos_movimiento(producto, cantidad="200"))
        with self.assertRaises(ValidationError):
            self.confirmar(borrador)
        self.assertEqual(MovimientoStock.objects.count(), 1)

    def test_rollback_del_catalogo_si_falla_auditoria_confirmacion(self):
        borrador = self.preparar_servicio()
        original = EventoAuditoria.objects.create
        def fallar(**kwargs):
            if kwargs["operacion"] == "borrador.confirmado":
                raise RuntimeError("Prueba")
            return original(**kwargs)
        with patch.object(EventoAuditoria.objects, "create", side_effect=fallar):
            with self.assertRaises(RuntimeError):
                self.confirmar(borrador)
        self.assertFalse(Servicio.objects.exists())
        borrador.refresh_from_db()
        self.assertEqual(borrador.estado, "pendiente")

    def test_herramienta_no_puede_confirmar_ni_ejecutar_sql(self):
        for nombre in ("confirmar", "ejecutar_sql", "eliminar_producto"):
            with self.assertRaises(ValidationError):
                ejecutar_herramienta(conversacion=self.conv, nombre=nombre, args={}, observados=set())

    def test_argumentos_extra_y_catalogo_sin_consultar_rechazados(self):
        args = {"id": None, **datos_servicio()}
        with self.assertRaises(ValidationError):
            ejecutar_herramienta(conversacion=self.conv, nombre="preparar_servicio", args={**args, "sql": "DROP TABLE"}, observados=set())
        servicio = Servicio.objects.create(**datos_servicio())
        with self.assertRaises(ValidationError):
            ejecutar_herramienta(conversacion=self.conv, nombre="preparar_servicio", args={**args, "id": servicio.pk}, observados=set())
        self.assertFalse(Borrador.objects.exists())

    def test_busqueda_con_homonimos_y_campos_null_conservan_edicion(self):
        uno = Servicio.objects.create(**datos_servicio(descripcion="Texto completo"))
        Servicio.objects.create(**datos_servicio(precio_base="300"))
        vistos = set()
        resultados = ejecutar_herramienta(conversacion=self.conv, nombre="buscar_catalogo", args={"tipo": "servicio", "busqueda": "Corte", "id": None, "solo_stock_bajo": False}, observados=vistos)
        self.assertEqual(len(resultados["resultados"]), 2)
        ejecutar_herramienta(conversacion=self.conv, nombre="preparar_servicio", args={"id": uno.pk, "nombre": None, "descripcion": None, "duracion_minutos": None, "precio_base": "290", "activo": None}, observados=vistos)
        borrador = Borrador.objects.get()
        self.assertEqual(borrador.datos["descripcion"], "Texto completo")
        self.confirmar(borrador)
        uno.refresh_from_db()
        self.assertEqual(str(uno.precio_base), "290.00")

    @override_settings(OPENAI_API_KEY="clave-privada-de-prueba")
    def test_responses_tool_loop_prepara_sin_confirmar_y_no_guarda_en_openai(self):
        api = MagicMock()
        api.responses.create.side_effect = [llamada("preparar_servicio", {"id": None, **datos_servicio()}), respuesta("Borrador preparado. Revisa y confirma.")]
        conversar(conversacion=self.conv, texto="Agrega corte por 250 en 45 minutos", cliente_api=api)
        self.assertEqual(Borrador.objects.count(), 1)
        self.assertFalse(Servicio.objects.exists())
        self.assertEqual(api.responses.create.call_count, 2)
        for call in api.responses.create.call_args_list:
            self.assertFalse(call.kwargs["store"])
            self.assertFalse(call.kwargs["parallel_tool_calls"])
            self.assertNotIn("clave-privada", json.dumps(call.kwargs))

    def test_clave_ausente_y_presupuesto_diario_no_llaman_api(self):
        with override_settings(OPENAI_API_KEY=""):
            with self.assertRaises(ErrorAsistente):
                conversar(conversacion=self.conv, texto="Hola")
        api = MagicMock()
        Mensaje.objects.create(conversacion=self.conv, rol="user", texto="Prueba")
        with override_settings(OPENAI_DAILY_REQUEST_LIMIT=1):
            with self.assertRaises(ErrorAsistente):
                conversar(conversacion=self.conv, texto="Hola", cliente_api=api)
        api.responses.create.assert_not_called()

    def test_precio_con_moneda_rechazado_y_correccion_del_modelo_crea_un_borrador(self):
        api = MagicMock()
        api.responses.create.side_effect = [
            llamada("preparar_servicio", {"id": None, **datos_servicio(precio_base="$250 MXN")}),
            llamada("preparar_servicio", {"id": None, **datos_servicio(precio_base="250.00")}, call_id="call_2"),
            respuesta("Borrador preparado para revisar."),
        ]
        conversar(conversacion=self.conv, texto="Corte por $250, 45 minutos", cliente_api=api)
        self.assertEqual(Borrador.objects.count(), 1)
        self.assertFalse(Servicio.objects.exists())
        self.assertEqual(Borrador.objects.get().datos["precio_base"], "250.00")
        precio = next(tool for tool in TOOLS if tool["name"] == "preparar_servicio")["parameters"]["properties"]["precio_base"]
        self.assertIn("pattern", precio)

    def test_error_de_conexion_o_autenticacion_no_filtra_clave_y_libera_turno(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        errors = [APIConnectionError(request=request), AuthenticationError("clave-super-secreta", response=httpx.Response(401, request=request), body=None)]
        for error in errors:
            api = MagicMock()
            api.responses.create.side_effect = error
            texto = conversar(conversacion=self.conv, texto="Hola", cliente_api=api)
            self.assertNotIn("super-secreta", texto)
            self.conv.refresh_from_db()
            self.assertIsNone(self.conv.ocupada_hasta)
        self.assertFalse(Servicio.objects.exists())

    def test_permiso_de_asistente_no_otorga_permisos_de_negocio(self):
        from django.contrib.auth.models import Permission
        usuario = get_user_model().objects.create_user(username="lectura")
        usuario.user_permissions.add(Permission.objects.get(codename="usar_asistente"))
        conv = Conversacion.objects.create(usuario=usuario, sesion="otra")
        with self.assertRaises(PermissionDenied):
            preparar(conversacion=conv, tipo="servicio", entidad_id=None, datos=datos_servicio())

    def test_confirmacion_http_csrf_y_edicion_separada(self):
        navegador = Client(enforce_csrf_checks=True)
        navegador.force_login(self.actor)
        navegador.get(reverse("asistente:chat"))
        conv = Conversacion.objects.get(usuario=self.actor, sesion=navegador.session.session_key)
        borrador = preparar(conversacion=conv, tipo="servicio", entidad_id=None, datos=datos_servicio())
        url = reverse("asistente:borrador", args=[borrador.pk])
        pagina = navegador.get(url)
        self.assertContains(pagina, "Confirmar y guardar")
        self.assertFalse(Servicio.objects.exists())
        token = pagina.context["confirmacion"]
        self.assertEqual(navegador.post(url, {"accion": "confirmar", "confirmacion": token}).status_code, 403)
        csrf = navegador.cookies["csrftoken"].value
        self.assertEqual(navegador.post(url, {"accion": "editar", "version_borrador": 1, **datos_servicio(precio_base="280"), "csrfmiddlewaretoken": csrf}).status_code, 302)
        self.assertFalse(Servicio.objects.exists())
        pagina = navegador.get(url)
        response = navegador.post(url, {"accion": "confirmar", "confirmacion": pagina.context["confirmacion"], "csrfmiddlewaretoken": csrf})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(str(Servicio.objects.get().precio_base), "280.00")

    @override_settings(OPENAI_API_KEY="clave-privada-de-prueba")
    def test_interfaz_escapa_html_y_no_expone_clave(self):
        self.client.force_login(self.actor)
        conv = Conversacion.objects.create(usuario=self.actor, sesion=self.client.session.session_key)
        Mensaje.objects.create(conversacion=conv, rol="assistant", texto="<script>alert(1)</script>")
        response = self.client.get(reverse("asistente:chat"))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "clave-privada-de-prueba")
        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_esquemas_estrictos_todos_campos_requeridos(self):
        for tool in TOOLS:
            self.assertTrue(tool["strict"])
            self.assertFalse(tool["parameters"]["additionalProperties"])
            self.assertCountEqual(tool["parameters"]["required"], tool["parameters"]["properties"])
