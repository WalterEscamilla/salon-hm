from decimal import Decimal
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.inventario.models import OpcionInventario, Producto
from apps.inventario.tests_presentation import datos_presentacion
from .models import Borrador, Conversacion
from .openai_service import TOOLS, conversar, ejecutar_herramienta
from .services import confirmar, preparar, token_confirmacion
from .tests import llamada, respuesta


class PresentacionAsistenteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="presentacion-ia", password="SoloPruebas123!")

    def setUp(self):
        self.client.force_login(self.actor)
        self.conv = Conversacion.objects.create(usuario=self.actor, sesion=self.client.session.session_key)

    def test_ciclo_de_herramientas_botellas_y_minimo_correctos(self):
        schema = next(tool for tool in TOOLS if tool["name"] == "preparar_producto")["parameters"]
        args = {campo: None for campo in schema["properties"]}
        args.update({k: v for k, v in datos_presentacion().items() if k in args})
        args.update(stock_minimo=None, modo_cantidad="envases")
        api = MagicMock()
        api.responses.create.side_effect = [llamada("preparar_producto", args), respuesta("Propuesta preparada.")]
        conversar(conversacion=self.conv, texto="Kuul 30 vol: 870 ml por botella, 65 pesos, 3.5 botellas y aviso cuando quede una.", cliente_api=api)
        borrador = Borrador.objects.get()
        self.assertEqual(borrador.datos["minimo_presentaciones"], "1")
        self.assertEqual(Decimal(borrador.datos["stock_minimo"]), Decimal("870"))
        self.assertFalse(Producto.objects.exists())
        self.assertContains(self.client.get(reverse("asistente:borrador", args=[borrador.pk])), "3.5 Botellas")
        token = token_confirmacion(borrador)
        for _ in range(2):
            confirmar(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, token=token)
        producto = Producto.objects.get()
        self.assertEqual(producto.existencias, 3045)
        self.assertEqual(producto.stock_minimo, 870)

    def test_modificar_borrador_con_tercio_conserva_fraccion_hasta_confirmar(self):
        borrador = preparar(conversacion=self.conv, tipo="producto", entidad_id=None,
            datos=datos_presentacion(presentacion="Tubos", unidad="g", contenido_envase="90"))
        datos = {campo: valor if valor is not None else "" for campo, valor in borrador.datos.items()}
        datos.pop("cantidad_inicial")
        datos.update(accion="editar", version_borrador=borrador.version,
            cantidad_inicial_0="0", cantidad_inicial_1="1/3")
        url = reverse("asistente:borrador", args=[borrador.pk])
        self.assertRedirects(self.client.post(url, datos), url)
        borrador.refresh_from_db()
        self.assertEqual(borrador.datos["cantidad_inicial"], "1/3")
        pagina = self.client.get(url)
        self.assertContains(pagina, '<option value="1/3" selected>')
        self.assertContains(pagina, "30 g")
        self.assertFalse(Producto.objects.exists())
        token = token_confirmacion(borrador)
        for _ in range(2):
            confirmar(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, token=token)
        producto = Producto.objects.get()
        self.assertEqual(producto.existencias, 30)
        self.assertEqual(producto.movimientos.count(), 1)
        self.assertEqual(producto.stock_minimo, 90)

    def test_opciones_personalizadas_se_agregan_despues_de_confirmar(self):
        borrador = preparar(conversacion=self.conv, tipo="producto", entidad_id=None,
            datos=datos_presentacion(presentacion="Frascos", unidad="oz", contenido_envase="2"))
        self.assertFalse(OpcionInventario.objects.filter(nombre="Frascos").exists())
        self.assertFalse(OpcionInventario.objects.filter(nombre="oz").exists())
        confirmar(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, token=token_confirmacion(borrador))
        self.assertEqual(Producto.objects.get().existencias, 7)
        self.assertTrue(OpcionInventario.objects.filter(nombre="Frascos").exists())
        self.assertTrue(OpcionInventario.objects.filter(nombre="oz").exists())

    def test_edicion_de_precio_con_null_conserva_aviso_y_no_recuenta(self):
        borrador = preparar(conversacion=self.conv, tipo="producto", entidad_id=None, datos=datos_presentacion())
        confirmar(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, token=token_confirmacion(borrador))
        producto = Producto.objects.get()
        schema = next(tool for tool in TOOLS if tool["name"] == "preparar_producto")["parameters"]
        args = {campo: None for campo in schema["properties"]}
        args.update(id=producto.pk, costo_envase="70")
        ejecutar_herramienta(conversacion=self.conv, nombre="preparar_producto", args=args, observados={("producto", producto.pk)})
        editar = Borrador.objects.exclude(pk=borrador.pk).get()
        self.assertEqual(self.client.get(reverse("asistente:borrador", args=[editar.pk])).status_code, 200)
        confirmar(borrador_id=editar.pk, actor=self.actor, sesion=self.conv.sesion, token=token_confirmacion(editar))
        producto.refresh_from_db()
        self.assertEqual(producto.costo_envase, Decimal("70"))
        self.assertEqual(producto.stock_minimo, 870)
        self.assertEqual(producto.existencias, 3045)
