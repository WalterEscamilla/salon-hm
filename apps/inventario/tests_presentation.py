from decimal import Decimal
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.auditoria.models import EventoAuditoria
from apps.finanzas.models import BaseFinanciera, Gasto
from .constants import OptionType
from .forms import ProductoPresentacionForm
from .models import MovimientoStock, OpcionInventario, Producto
from .services import guardar_producto, registrar_movimiento
from .tests import datos_movimiento, datos_producto


def datos_presentacion(**extra):
    return datos_producto(**{
        "nombre": "Peróxido 30 vol", "marca": "Kuul", "presentacion": "Botellas",
        "unidad": "ml", "contenido_envase": "870", "costo_envase": "65",
        "cantidad_inicial": "3.5", "minimo_presentaciones": "1",
        "clave_alta": str(uuid.uuid4()), **extra,
    })


class PresentacionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="presentacion-test", password="SoloPruebas123!")

    def test_botellas_870_stock_y_aviso_usan_presentaciones(self):
        saldo = BaseFinanciera.objects.get(pk=1).saldo_inicial
        producto = guardar_producto(actor=self.actor, datos=datos_presentacion(modo_cantidad="base", stock_minimo="1"))
        self.assertEqual(producto.existencias, Decimal("3045"))
        self.assertEqual(producto.envases_equivalentes, Decimal("3.5"))
        self.assertEqual(producto.stock_minimo, Decimal("870"))
        self.assertEqual(producto.minimo_presentaciones, Decimal("1"))
        self.assertEqual(producto.costo_envase, Decimal("65"))
        self.assertFalse(producto.stock_bajo)
        registrar_movimiento(actor=self.actor, producto_id=producto.pk, datos=datos_movimiento(producto, tipo="salida", cantidad="2175"))
        producto.refresh_from_db()
        self.assertEqual(producto.envases_equivalentes, 1)
        self.assertTrue(producto.stock_bajo)
        self.assertEqual(BaseFinanciera.objects.get(pk=1).saldo_inicial, saldo)
        self.assertFalse(Gasto.objects.exists())

    def test_tubos_90_g_conteo_y_visualizacion(self):
        producto = guardar_producto(actor=self.actor, datos=datos_presentacion(nombre="Tinte 7.5", presentacion="Tubos", unidad="g", contenido_envase="90", costo_envase="49"))
        self.assertEqual(producto.existencias, 315)
        self.assertEqual(producto.stock_minimo, 90)
        self.client.force_login(self.actor)
        for url in (reverse("inventario:listado"), reverse("inventario:detalle", args=[producto.pk])):
            page = self.client.get(url)
            self.assertContains(page, "3.5 Tubos")
            self.assertContains(page, "315 g")
        self.assertContains(self.client.get(reverse("inventario:detalle", args=[producto.pk])), "1 Tubos")

    def test_litros_se_conservan_y_movimientos_admiten_la_unidad(self):
        producto = guardar_producto(actor=self.actor, datos=datos_presentacion(unidad="l", contenido_envase="0.870"))
        self.assertEqual(producto.existencias, Decimal("3.045"))
        self.assertEqual(producto.stock_minimo, Decimal("0.870"))
        registrar_movimiento(actor=self.actor, producto_id=producto.pk, datos=datos_movimiento(producto, tipo="salida", cantidad="0.045"))
        producto.refresh_from_db()
        self.assertEqual(producto.existencias, Decimal("3"))
        self.assertEqual(producto.unidad, "l")
        self.assertEqual(producto.movimientos.first().unidad, "l")

    def test_nuevas_opciones_solo_se_agregan_al_guardar_y_sin_duplicados(self):
        datos = datos_presentacion(presentacion="Garrafones", unidad="oz", contenido_envase="100")
        form = ProductoPresentacionForm(datos)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(OpcionInventario.objects.filter(nombre="Garrafones").exists())
        uno = guardar_producto(actor=self.actor, datos=form.cleaned_data)
        self.assertEqual(guardar_producto(actor=self.actor, datos=form.cleaned_data).pk, uno.pk)
        guardar_producto(actor=self.actor, datos=datos_presentacion(presentacion="garrafones", unidad="oz", contenido_envase="100"))
        self.assertEqual(OpcionInventario.objects.filter(tipo=OptionType.PRESENTATION, nombre_normalizado="garrafones").count(), 1)
        self.assertEqual(OpcionInventario.objects.filter(tipo=OptionType.UNIT, nombre="oz").count(), 1)
        self.client.force_login(self.actor)
        pagina = self.client.get(reverse("inventario:nuevo"))
        self.assertContains(pagina, '<option value="Garrafones">Garrafones</option>')
        self.assertContains(pagina, '<option value="oz">oz</option>')

    def test_limites_precision_y_datos_obligatorios_sin_escrituras(self):
        for extra in ({"contenido_envase": None}, {"minimo_presentaciones": "-1"},
                      {"minimo_presentaciones": "NaN"}, {"contenido_envase": "0.001", "minimo_presentaciones": "0.001"},
                      {"contenido_envase": "999999999.999", "minimo_presentaciones": "99999999999.999"},
                      {"unidad": "u" * 25}, {"presentacion": "p" * 81}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                guardar_producto(actor=self.actor, datos=datos_presentacion(**extra))
        self.assertFalse(Producto.objects.exists())

    def test_rollback_tambien_desestima_opciones_nuevas(self):
        with patch.object(EventoAuditoria.objects, "create", side_effect=RuntimeError("fallo de auditoría")):
            with self.assertRaises(RuntimeError):
                guardar_producto(actor=self.actor, datos=datos_presentacion(presentacion="Bolsitas", unidad="kg"))
        self.assertFalse(Producto.objects.exists())
        self.assertFalse(OpcionInventario.objects.filter(nombre="Bolsitas").exists())
        self.assertFalse(OpcionInventario.objects.filter(nombre="kg").exists())

    def test_edicion_conserva_conteo_y_presentacion_y_permite_precio_y_aviso(self):
        producto = guardar_producto(actor=self.actor, datos=datos_presentacion())
        editar = datos_presentacion(cantidad_inicial=None, costo_envase="70", minimo_presentaciones="2")
        guardar_producto(actor=self.actor, producto_id=producto.pk, datos=editar)
        producto.refresh_from_db()
        self.assertEqual(producto.existencias, 3045)
        self.assertEqual(producto.stock_minimo, 1740)
        for cambio in ({"contenido_envase": "1000"}, {"presentacion": "Tubos"}, {"unidad": "l"}):
            with self.assertRaises(ValidationError):
                guardar_producto(actor=self.actor, producto_id=producto.pk, datos={**editar, **cambio})
        self.client.force_login(self.actor)
        page = self.client.get(reverse("inventario:editar", args=[producto.pk]))
        self.assertEqual(page.context["form"]["minimo_presentaciones"].value(), 2)
        self.assertNotContains(page, 'name="cantidad_inicial"')

    def test_formulario_http_no_exige_modo_y_no_duplica(self):
        self.client.force_login(self.actor)
        datos = datos_presentacion()
        datos.pop("stock_minimo")
        page = self.client.get(reverse("inventario:nuevo"))
        self.assertContains(page, '<select name="presentacion"')
        self.assertContains(page, '<select name="unidad"')
        self.assertEqual(page.context["form"].fields["modo_cantidad"].widget.input_type, "hidden")
        for _ in range(2):
            post = self.client.post(reverse("inventario:nuevo"), datos)
            self.assertEqual(post.status_code, 302)
        producto = Producto.objects.get()
        self.assertEqual(producto.existencias, 3045)
        self.assertEqual(producto.stock_minimo, 870)
        self.assertEqual(MovimientoStock.objects.count(), 1)

    def test_permiso_no_crea_opciones_y_legacy_conserva_cantidad(self):
        usuario = get_user_model().objects.create_user(username="sinpermiso-presentacion")
        with self.assertRaises(PermissionDenied):
            guardar_producto(actor=usuario, datos=datos_presentacion(presentacion="Cubetas"))
        self.assertFalse(OpcionInventario.objects.filter(nombre="Cubetas").exists())
        legacy = guardar_producto(actor=self.actor, datos=datos_producto(cantidad_inicial="3.5", modo_cantidad="base"))
        self.assertEqual(legacy.existencias, Decimal("3.5"))
        self.assertEqual(legacy.stock_minimo, 200)
        self.assertEqual(legacy.presentacion, "")

    def test_indicar_presentacion_en_producto_anterior_conserva_el_aviso(self):
        legacy = guardar_producto(actor=self.actor, datos=datos_producto(contenido_envase="870", stock_minimo="870"))
        datos = datos_producto(presentacion="Botellas", contenido_envase="870", stock_minimo="870")
        guardar_producto(actor=self.actor, producto_id=legacy.pk, datos=datos)
        legacy.refresh_from_db()
        self.assertEqual(legacy.stock_minimo, 870)
        self.assertEqual(legacy.minimo_presentaciones, 1)
        self.assertEqual(legacy.existencias, 0)
