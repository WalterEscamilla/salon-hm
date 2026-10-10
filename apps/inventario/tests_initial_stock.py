from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.auditoria.models import EventoAuditoria
from apps.finanzas.models import BaseFinanciera, Gasto
from .forms import ProductoForm
from .models import MovimientoStock, Producto
from .services import guardar_producto
from .tests import datos_producto


def datos_iniciales(**extra):
    return datos_producto(**{"nombre": "Peróxido 30 vol", "descripcion": "30 vol", "contenido_envase": "875", "costo_envase": "65", "cantidad_inicial": "3.5", "modo_cantidad": "envases", "clave_alta": str(uuid.uuid4()), **extra})


class ConteoInicialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="conteo-prueba", password="SoloPruebas123!")

    def test_peroxido_con_tres_botellas_y_media_sin_movimientos_financieros(self):
        saldo = BaseFinanciera.objects.get(pk=1).saldo_inicial
        producto = guardar_producto(actor=self.actor, datos=datos_iniciales())
        self.assertEqual(producto.existencias, Decimal("3062.500"))
        self.assertEqual(producto.envases_equivalentes, Decimal("3.5"))
        self.assertEqual(producto.contenido_envase, Decimal("875"))
        self.assertEqual(producto.costo_envase, Decimal("65"))
        movimiento = MovimientoStock.objects.get()
        self.assertEqual(movimiento.tipo, "ajuste")
        self.assertEqual(movimiento.cantidad, Decimal("3062.500"))
        self.assertEqual(movimiento.costo_por_unidad, Decimal("0.074286"))
        self.assertEqual(BaseFinanciera.objects.get(pk=1).saldo_inicial, saldo)
        self.assertFalse(Gasto.objects.exists())

    def test_reenvio_no_duplica_y_cambio_con_misma_clave_se_rechaza(self):
        datos = datos_iniciales()
        primero = guardar_producto(actor=self.actor, datos=datos)
        segundo = guardar_producto(actor=self.actor, datos=datos)
        self.assertEqual(primero.pk, segundo.pk)
        self.assertEqual(Producto.objects.count(), 1)
        self.assertEqual(MovimientoStock.objects.count(), 1)
        with self.assertRaises(ValidationError):
            guardar_producto(actor=self.actor, datos={**datos, "cantidad_inicial": "4"})

    def test_clave_tambien_protege_alta_sin_conteo(self):
        datos = datos_iniciales(cantidad_inicial=None)
        primero = guardar_producto(actor=self.actor, datos=datos)
        self.assertEqual(guardar_producto(actor=self.actor, datos=datos).pk, primero.pk)
        self.assertFalse(MovimientoStock.objects.exists())

    def test_cantidad_base_y_cero_explicito(self):
        producto = guardar_producto(actor=self.actor, datos=datos_iniciales(cantidad_inicial="120.125", modo_cantidad="base"))
        self.assertEqual(producto.existencias, Decimal("120.125"))
        cero = guardar_producto(actor=self.actor, datos=datos_iniciales(cantidad_inicial="0"))
        self.assertEqual(cero.existencias, 0)
        self.assertEqual(cero.movimientos.count(), 1)

    def test_unidades_completas_y_envases_pesados(self):
        piezas = guardar_producto(actor=self.actor, datos=datos_iniciales(unidad="unidad", contenido_envase="1", cantidad_inicial="3", modo_cantidad="base"))
        self.assertEqual(piezas.existencias, 3)
        gramos = guardar_producto(actor=self.actor, datos=datos_iniciales(unidad="g", contenido_envase="250", cantidad_inicial="1.5"))
        self.assertEqual(gramos.existencias, Decimal("375"))

    def test_validaciones_no_crean_registros(self):
        casos = [
            {"contenido_envase": None}, {"cantidad_inicial": "-1"},
            {"unidad": "unidad", "contenido_envase": "1"},
            {"contenido_envase": "0.001", "cantidad_inicial": "0.001"},
            {"contenido_envase": "999999999.999", "cantidad_inicial": "99999999999.999"},
            {"cantidad_inicial": "NaN"}, {"activo": False}, {"modo_cantidad": "inventado"},
        ]
        for extra in casos:
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                guardar_producto(actor=self.actor, datos=datos_iniciales(**extra))
        self.assertFalse(Producto.objects.exists())
        self.assertFalse(MovimientoStock.objects.exists())

    def test_producto_y_conteo_se_revierten_juntos_si_falla_auditoria(self):
        original = EventoAuditoria.objects.create
        def crear(**kwargs):
            if kwargs.get("operacion") == "stock.movimiento":
                raise RuntimeError("Fallo simulado de auditoría")
            return original(**kwargs)
        with patch.object(EventoAuditoria.objects, "create", side_effect=crear), self.assertRaises(RuntimeError):
            guardar_producto(actor=self.actor, datos=datos_iniciales())
        self.assertFalse(Producto.objects.exists())
        self.assertFalse(MovimientoStock.objects.exists())

    def test_permiso_movimientos_requerido_para_conteo(self):
        usuario = get_user_model().objects.create_user(username="solo-producto")
        usuario.user_permissions.add(Permission.objects.get(codename="add_producto"))
        with self.assertRaises(PermissionDenied):
            guardar_producto(actor=usuario, datos=datos_iniciales())
        self.assertFalse(Producto.objects.exists())

    def test_editar_datos_conserva_stock_y_no_admite_reinicializarlo(self):
        producto = guardar_producto(actor=self.actor, datos=datos_iniciales())
        self.assertNotIn("cantidad_inicial", ProductoForm(instance=producto).fields)
        editar = datos_producto(nombre=producto.nombre, contenido_envase="875", costo_envase="70")
        guardado = guardar_producto(actor=self.actor, producto_id=producto.pk, datos=editar)
        self.assertEqual(guardado.existencias, Decimal("3062.500"))
        self.assertEqual(MovimientoStock.objects.count(), 1)
        with self.assertRaises(ValidationError):
            guardar_producto(actor=self.actor, producto_id=producto.pk, datos={**editar, "cantidad_inicial": "10"})

    def test_formulario_http_conteo_y_error_cerca_del_campo(self):
        self.client.force_login(self.actor)
        url = reverse("inventario:nuevo")
        pagina = self.client.get(url)
        self.assertContains(pagina, 'name="cantidad_inicial"')
        self.assertContains(pagina, 'name="modo_cantidad"')
        self.assertContains(pagina, 'name="clave_alta"')
        datos = datos_iniciales(contenido_envase="")
        respuesta = self.client.post(url, datos)
        self.assertContains(respuesta, "Indica cuánto trae cada botella")
        self.assertEqual(respuesta.context["form"]["cantidad_inicial"].value(), "3.5")
        datos["contenido_envase"] = "875"
        respuesta = self.client.post(url, datos)
        producto = Producto.objects.get()
        self.assertRedirects(respuesta, reverse("inventario:detalle", args=[producto.pk]))
        detalle = self.client.get(respuesta.url)
        self.assertContains(detalle, "Botellas o envases equivalentes")


class AltaConcurrenteTests(TransactionTestCase):
    def test_doble_envio_simultaneo_crea_un_producto_y_un_conteo(self):
        actor = get_user_model().objects.create_superuser(username="alta-concurrente", password="SoloPruebas123!")
        datos = datos_iniciales()
        barrera = Barrier(2)
        def ejecutar(_):
            close_old_connections()
            try:
                usuario = get_user_model().objects.get(pk=actor.pk)
                barrera.wait(timeout=10)
                return guardar_producto(actor=usuario, datos=datos).pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(ejecutar, range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(Producto.objects.count(), 1)
        self.assertEqual(MovimientoStock.objects.count(), 1)
        self.assertEqual(Producto.objects.get().existencias, Decimal("3062.500"))
