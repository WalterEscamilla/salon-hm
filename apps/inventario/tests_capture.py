"""Regresiones de la captura por fracciones, opciones y correcciones iniciales."""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.auditoria.models import EventoAuditoria
from apps.finanzas.models import BaseFinanciera, Gasto
from .constants import NEW_OPTION, OptionType, PRODUCT_PRESENTATION_CORRECTED
from .forms import ProductoPresentacionForm
from .models import MovimientoStock, OpcionInventario, Producto
from .services import guardar_producto, registrar_movimiento
from .tests import datos_movimiento
from .tests_presentation import datos_presentacion


class CapturaInventarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser("captura-test", password="SoloPruebas123!")

    def setUp(self):
        self.client.force_login(self.actor)

    def test_fracciones_y_revalidacion_sin_aproximar_tercios(self):
        for fraccion, contenido, esperado in (("1/4", "90", "22.5"),
                ("1/3", "90", "30"), ("1/2", "90", "45"),
                ("2/3", "90", "60"), ("3/4", "90", "67.5"),
                ("1/3", "870", "290")):
            with self.subTest(fraccion=fraccion, contenido=contenido):
                datos = datos_presentacion(cantidad_inicial=None, contenido_envase=contenido)
                datos.pop("cantidad_inicial")
                datos.update(cantidad_inicial_0="0", cantidad_inicial_1=fraccion)
                form = ProductoPresentacionForm(datos)
                self.assertTrue(form.is_valid(), form.errors)
                producto = guardar_producto(actor=self.actor, datos=form.cleaned_data)
                self.assertEqual(producto.existencias, Decimal(esperado))
                self.assertEqual(guardar_producto(actor=self.actor, datos=form.cleaned_data).pk, producto.pk)
                self.assertEqual(producto.movimientos.count(), 1)

    def test_completos_mas_fraccion_y_conteo_pendiente_o_cero(self):
        for enteros, fraccion, esperado in (("3", "1/2", 3045), ("3", "1/3", 2900),
                ("", "1/3", 290), ("0", "", 0), ("", "", None)):
            with self.subTest(enteros=enteros, fraccion=fraccion):
                datos = datos_presentacion()
                datos.pop("cantidad_inicial")
                datos.update(cantidad_inicial_0=enteros, cantidad_inicial_1=fraccion)
                post = self.client.post(reverse("inventario:nuevo"), datos)
                self.assertEqual(post.status_code, 302)
                producto = Producto.objects.latest("pk")
                self.assertEqual(producto.existencias, esperado or 0)
                self.assertEqual(producto.movimientos.count(), int(esperado is not None))

    def test_fracciones_invalidas_o_precision_no_crean_datos(self):
        for cambio in ({"cantidad_inicial_0": "-1", "cantidad_inicial_1": "1/2"},
                {"cantidad_inicial_0": "NaN", "cantidad_inicial_1": "1/2"},
                {"cantidad_inicial_0": "1", "cantidad_inicial_1": "fraude"},
                {"cantidad_inicial_0": "0", "cantidad_inicial_1": "1/3", "contenido_envase": "100"}):
            with self.subTest(cambio=cambio):
                datos = datos_presentacion()
                datos.pop("cantidad_inicial")
                form = ProductoPresentacionForm({**datos, **cambio})
                self.assertFalse(form.is_valid())
                self.assertIn("cantidad_inicial", form.errors)
        self.assertFalse(Producto.objects.exists())

    def test_desplegables_nueva_opcion_persistencia_y_recuperacion(self):
        pagina = self.client.get(reverse("inventario:nuevo"))
        self.assertContains(pagina, '<select name="unidad"')
        self.assertContains(pagina, '<option value="g">g</option>')
        self.assertContains(pagina, '<select name="presentacion"')
        self.assertIsNone(pagina.context["form"]["unidad"].value())
        datos = datos_presentacion(presentacion=NEW_OPTION, unidad=NEW_OPTION,
            presentacion_nueva="Frascos", unidad_nueva="kg", contenido_envase="2")
        incorrecto = self.client.post(reverse("inventario:nuevo"), {**datos, "contenido_envase": ""})
        self.assertEqual(incorrecto.status_code, 200)
        self.assertContains(incorrecto, '<option value="Frascos" selected>Frascos</option>')
        self.assertFalse(OpcionInventario.objects.filter(nombre="Frascos").exists())
        self.assertEqual(self.client.post(reverse("inventario:nuevo"), datos).status_code, 302)
        nuevo = self.client.get(reverse("inventario:nuevo"))
        self.assertContains(nuevo, '<option value="Frascos">Frascos</option>')
        self.assertContains(nuevo, '<option value="kg">kg</option>')
        self.assertEqual(OpcionInventario.objects.filter(tipo=OptionType.UNIT, nombre="kg").count(), 1)
        self.assertEqual(Producto.objects.get().existencias, 7)

    def test_corregir_ml_por_g_preserva_cuarto_de_tubo_historial_y_finanzas(self):
        producto = guardar_producto(actor=self.actor, datos=datos_presentacion(
            presentacion="Tubos", contenido_envase="90", cantidad_inicial="0.25"))
        anterior = producto.movimientos.get()
        saldo = BaseFinanciera.objects.get(pk=1).saldo_inicial
        editar = datos_presentacion(presentacion="Tubos", contenido_envase="90",
            cantidad_inicial="", unidad="g", corregir_presentacion=True)
        self.assertEqual(self.client.post(reverse("inventario:editar", args=[producto.pk]), editar).status_code, 302)
        producto.refresh_from_db()
        anterior.refresh_from_db()
        self.assertEqual(producto.unidad, "g")
        self.assertEqual(producto.existencias, Decimal("22.5"))
        self.assertEqual(producto.envases_equivalentes, Decimal("0.25"))
        self.assertEqual(producto.minimo_presentaciones, 1)
        self.assertEqual(anterior.unidad, "ml")
        self.assertEqual(anterior.saldo_nuevo, Decimal("22.5"))
        self.assertEqual(producto.movimientos.first().unidad, "g")
        self.assertEqual(producto.movimientos.count(), 2)
        audit = EventoAuditoria.objects.get(operacion=PRODUCT_PRESENTATION_CORRECTED)
        self.assertEqual(audit.cambios["antes"]["unidad"], "ml")
        self.assertEqual(audit.cambios["despues"]["unidad"], "g")
        self.assertFalse(Gasto.objects.exists())
        self.assertEqual(BaseFinanciera.objects.get(pk=1).saldo_inicial, saldo)
        # Reenviar no repite el ajuste ni cambia el saldo.
        guardar_producto(actor=self.actor, producto_id=producto.pk, datos=editar)
        self.assertEqual(producto.movimientos.count(), 2)

    def test_corregir_contenido_conserva_presentaciones_y_aviso(self):
        producto = guardar_producto(actor=self.actor, datos=datos_presentacion())
        editar = datos_presentacion(cantidad_inicial=None, contenido_envase="900", corregir_presentacion=True)
        guardar_producto(actor=self.actor, producto_id=producto.pk, datos=editar)
        producto.refresh_from_db()
        self.assertEqual(producto.existencias, 3150)
        self.assertEqual(producto.envases_equivalentes, Decimal("3.5"))
        self.assertEqual(producto.stock_minimo, 900)
        self.assertEqual(producto.movimientos.last().saldo_nuevo, 3045)

    def test_correccion_exige_confirmacion_permiso_y_conteo_inicial_sin_consumos(self):
        producto = guardar_producto(actor=self.actor, datos=datos_presentacion())
        editar = datos_presentacion(cantidad_inicial=None, unidad="g")
        with self.assertRaises(ValidationError):
            guardar_producto(actor=self.actor, producto_id=producto.pk, datos=editar)
        usuario = get_user_model().objects.create_user("solo-editar")
        usuario.user_permissions.add(Permission.objects.get(codename="change_producto"))
        with self.assertRaises(PermissionDenied):
            guardar_producto(actor=usuario, producto_id=producto.pk, datos={**editar, "corregir_presentacion": True})
        registrar_movimiento(actor=self.actor, producto_id=producto.pk, datos=datos_movimiento(producto, tipo="salida", cantidad="10"))
        with self.assertRaises(ValidationError):
            guardar_producto(actor=self.actor, producto_id=producto.pk, datos={**editar, "corregir_presentacion": True})
        producto.refresh_from_db()
        self.assertEqual(producto.unidad, "ml")
        self.assertEqual(producto.existencias, 3035)
        form = ProductoPresentacionForm(instance=producto)
        self.assertTrue(form.fields["unidad"].disabled)
        self.assertNotIn("corregir_presentacion", form.fields)

    def test_correccion_fallida_revierte_producto_movimientos_y_opciones(self):
        producto = guardar_producto(actor=self.actor, datos=datos_presentacion())
        with patch("apps.inventario.services.registrar_movimiento", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                guardar_producto(actor=self.actor, producto_id=producto.pk, datos=datos_presentacion(
                    cantidad_inicial=None, unidad="kg", corregir_presentacion=True))
        producto.refresh_from_db()
        self.assertEqual(producto.unidad, "ml")
        self.assertEqual(producto.movimientos.count(), 1)
        self.assertFalse(OpcionInventario.objects.filter(nombre="kg").exists())
