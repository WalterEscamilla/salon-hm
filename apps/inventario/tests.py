from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.auditoria.models import EventoAuditoria
from .models import MovimientoStock, Producto
from .services import guardar_producto, registrar_movimiento


def datos_producto(**extra):
    return {"nombre": "Peróxido", "marca": "Ejemplo", "descripcion": "20 vol", "unidad": "ml", "contenido_envase": "1000", "costo_envase": "120", "stock_minimo": "200", "activo": True, **extra}


def datos_movimiento(producto, **extra):
    return {"tipo": "entrada", "cantidad": "1000", "unidad": producto.unidad, "motivo": "Compra", "version": producto.version, "clave_operacion": str(uuid.uuid4()), **extra}


class InventarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="Marisol", password="ClaveParaPruebas123!")

    def producto(self, **extra):
        return guardar_producto(actor=self.actor, datos=datos_producto(**extra))

    def mover(self, producto, **extra):
        return registrar_movimiento(actor=self.actor, producto_id=producto.pk, datos=datos_movimiento(producto, **extra))

    def test_producto_costo_desconocido_y_stock_inicial_cero(self):
        producto = self.producto(costo_envase=None)
        self.assertIsNone(producto.costo_por_unidad)
        self.assertEqual(producto.existencias, 0)
        self.assertTrue(producto.stock_bajo)
        self.assertFalse(MovimientoStock.objects.exists())

    def test_decimal_entrada_consumo_y_ajuste_absoluto(self):
        producto = self.producto()
        self.mover(producto, cantidad="100.125")
        producto.refresh_from_db()
        consumo = self.mover(producto, tipo="salida", cantidad="0.125", motivo="Consumo")
        self.assertEqual(consumo.saldo_nuevo, Decimal("100.000"))
        producto.refresh_from_db()
        ajuste = self.mover(producto, tipo="ajuste", cantidad="80", motivo="Conteo físico")
        self.assertEqual(ajuste.saldo_nuevo, Decimal("80"))
        self.assertEqual(ajuste.saldo_anterior, Decimal("100"))

    def test_saldo_negativo_unidad_distinta_y_fraccion_de_unidades_rechazados(self):
        producto = self.producto()
        for extra in ({"tipo": "salida"}, {"unidad": "g"}, {"cantidad": "0"}, {"cantidad": "NaN"}):
            with self.assertRaises(ValidationError):
                self.mover(producto, **extra)
        unidad = self.producto(unidad="unidad")
        with self.assertRaises(ValidationError):
            self.mover(unidad, cantidad="1.5")
        self.assertFalse(MovimientoStock.objects.exists())

    def test_reintento_idempotente_y_clave_no_reutilizable(self):
        producto = self.producto()
        datos = datos_movimiento(producto)
        uno = registrar_movimiento(actor=self.actor, producto_id=producto.pk, datos=datos)
        dos = registrar_movimiento(actor=self.actor, producto_id=producto.pk, datos=datos)
        self.assertEqual(uno.pk, dos.pk)
        self.assertEqual(MovimientoStock.objects.count(), 1)
        with self.assertRaises(ValidationError):
            registrar_movimiento(actor=self.actor, producto_id=producto.pk, datos={**datos, "cantidad": "900"})

    def test_movimiento_conserva_costo_historico_o_desconocido(self):
        producto = self.producto()
        movimiento = self.mover(producto)
        self.assertEqual(movimiento.costo_por_unidad, Decimal("0.120000"))
        guardar_producto(actor=self.actor, producto_id=producto.pk, datos=datos_producto(costo_envase="200"))
        movimiento.refresh_from_db()
        self.assertEqual(movimiento.costo_por_unidad, Decimal("0.120000"))
        desconocido = self.producto(costo_envase=None)
        self.assertIsNone(self.mover(desconocido).costo_por_unidad)

    def test_unidad_con_historial_y_version_obsoleta(self):
        producto = self.producto()
        self.mover(producto)
        with self.assertRaises(ValidationError):
            guardar_producto(actor=self.actor, producto_id=producto.pk, datos=datos_producto(unidad="g"))
        with self.assertRaises(ValidationError):
            self.mover(producto)
        producto.refresh_from_db()
        self.assertEqual(producto.unidad, "ml")

    def test_permiso_y_rollback_auditoria(self):
        usuario = get_user_model().objects.create_user(username="sinpermiso")
        with self.assertRaises(PermissionDenied):
            guardar_producto(actor=usuario, datos=datos_producto())
        producto = self.producto()
        with patch.object(EventoAuditoria.objects, "create", side_effect=RuntimeError("Prueba")):
            with self.assertRaises(RuntimeError):
                self.mover(producto)
        producto.refresh_from_db()
        self.assertEqual(producto.existencias, 0)
        self.assertFalse(MovimientoStock.objects.exists())

    def test_formularios_y_historial_privados(self):
        self.assertEqual(self.client.get(reverse("inventario:listado")).status_code, 302)
        self.client.force_login(self.actor)
        response = self.client.post(reverse("inventario:nuevo"), datos_producto())
        producto = Producto.objects.get()
        self.assertRedirects(response, reverse("inventario:detalle", args=[producto.pk]))
        response = self.client.post(reverse("inventario:movimiento", args=[producto.pk]), datos_movimiento(producto))
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(reverse("inventario:detalle", args=[producto.pk])), "Compra")


class InventarioConcurrenteTests(TransactionTestCase):
    def test_dos_salidas_simultaneas_no_descontar_dos_veces(self):
        actor = get_user_model().objects.create_superuser(username="Marisol", password="ClaveParaPruebas123!")
        producto = guardar_producto(actor=actor, datos=datos_producto())
        registrar_movimiento(actor=actor, producto_id=producto.pk, datos=datos_movimiento(producto, cantidad="10"))
        producto.refresh_from_db()
        datos = datos_movimiento(producto, tipo="salida", cantidad="7")
        barrera = Barrier(2)

        def ejecutar():
            close_old_connections()
            try:
                usuario = get_user_model().objects.get(pk=actor.pk)
                barrera.wait(timeout=10)
                try:
                    registrar_movimiento(actor=usuario, producto_id=producto.pk, datos={**datos, "clave_operacion": str(uuid.uuid4())})
                    return "guardado"
                except ValidationError:
                    return "rechazado"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(lambda _: ejecutar(), range(2)))
        self.assertCountEqual(resultados, ["guardado", "rechazado"])
        producto.refresh_from_db()
        self.assertEqual(producto.existencias, Decimal("3"))
