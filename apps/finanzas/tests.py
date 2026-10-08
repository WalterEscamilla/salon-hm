from datetime import timedelta
from decimal import Decimal
import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.asistente.models import Borrador, Conversacion
from apps.asistente.openai_service import TOOLS, conversar, validar_argumentos
from apps.asistente.tests import llamada
from apps.atenciones.models import Atencion
from apps.atenciones.services import guardar_atencion
from apps.atenciones.tests import datos_visita
from apps.auditoria.models import EventoAuditoria
from apps.configuracion.models import ConfiguracionSalon
from .models import BaseFinanciera, Gasto
from .queries import resumen_financiero
from .services import anular_gasto, guardar_base, guardar_gasto


def datos_pago(**cambios):
    return {"fecha": timezone.localdate(), "concepto": "Luz semanal", "categoria": "luz", "importe": "200.00", "notas": "Pago de esta semana", "clave_operacion": uuid.uuid4(), "version": 1, **cambios}


class FinanzasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="Finanzas", password="SoloParaPruebas123!")
        cls.base, _ = BaseFinanciera.objects.get_or_create(pk=1)
        cls.base.fecha_inicio = timezone.localdate()
        cls.base.save()

    def visita(self, **cambios):
        return guardar_atencion(actor=self.actor, datos=datos_visita(**{"costo_materiales": "80", "otros_gastos": "0", **cambios}))

    def pago(self, datos=None, **kwargs):
        return guardar_gasto(actor=self.actor, datos=datos or datos_pago(), **kwargs)

    def test_base_disponible_no_es_ingreso_ni_gasto(self):
        resumen = resumen_financiero()
        self.assertEqual(resumen["saldo"], Decimal("10000"))
        self.assertEqual(resumen["ingresos"], Decimal("0"))
        self.assertEqual(resumen["gastos"], Decimal("0"))
        self.assertEqual(resumen["margen"], Decimal("0"))

    def test_luz_lampara_y_materiales_comprados_antes(self):
        self.pago()
        self.pago(datos_pago(concepto="Lámpara", categoria="equipo", importe="600"))
        visita = self.visita()
        self.assertEqual(visita.costo_total, Decimal("80"))
        self.assertEqual(visita.margen, Decimal("420"))
        resumen = resumen_financiero()
        self.assertEqual(resumen["saldo"], Decimal("9700"))
        self.assertEqual(resumen["pagos_visitas"], Decimal("0"))
        self.assertEqual(resumen["margen"], Decimal("420"))

    def test_compra_registrada_no_se_descuenta_otra_vez_al_usarla(self):
        self.pago(datos_pago(concepto="Tintes", categoria="materiales", importe="100"))
        self.visita(costo_materiales="100", otros_gastos="20")
        resumen = resumen_financiero()
        self.assertEqual(resumen["saldo"], Decimal("10400"))
        self.assertEqual(resumen["margen"], Decimal("380"))

    def test_gastos_pagados_en_visita_se_descuentan_una_vez(self):
        datos = datos_visita(costo_materiales="80", otros_gastos="20", gastos_pagados_en_visita=True)
        visita = guardar_atencion(actor=self.actor, datos=datos)
        self.assertEqual(guardar_atencion(actor=self.actor, datos=datos).pk, visita.pk)
        resumen = resumen_financiero()
        self.assertEqual(resumen["saldo"], Decimal("10400"))
        self.assertEqual(resumen["pagos_visitas"], Decimal("100"))
        self.assertFalse(Gasto.objects.exists())

    def test_corregir_visita_recalcula_sin_crear_otro_pago(self):
        visita = self.visita(gastos_pagados_en_visita=True)
        datos = datos_visita(cliente_id=visita.cliente_id, clave_operacion=visita.clave_operacion, version=visita.version, precio_cobrado="450", costo_materiales="90", otros_gastos="10", gastos_pagados_en_visita=True)
        guardar_atencion(actor=self.actor, atencion_id=visita.pk, datos=datos)
        resumen = resumen_financiero()
        self.assertEqual(resumen["saldo"], Decimal("10350"))
        self.assertEqual(Atencion.objects.count(), 1)
        self.assertFalse(Gasto.objects.exists())
        evento = EventoAuditoria.objects.get(operacion="atencion.editada")
        self.assertEqual(evento.cambios["finanzas_antes"]["costo_materiales"], "80.00")
        self.assertEqual(evento.cambios["finanzas_despues"]["costo_materiales"], "90")

    def test_costos_desconocidos_no_producen_margen_ficticio(self):
        visita = self.visita(costo_materiales=None, otros_gastos=None)
        self.assertIsNone(visita.costo_total)
        self.assertIsNone(visita.margen)
        resumen = resumen_financiero()
        self.assertEqual(resumen["saldo"], Decimal("10500"))
        self.assertEqual(resumen["visitas_pendientes"], 1)
        self.assertEqual(resumen["visitas_completas"], 0)

    def test_precio_desconocido_y_gratis_se_distinguen(self):
        self.visita(precio_cobrado=None)
        gratis = self.visita(precio_cobrado="0", costo_materiales="0", otros_gastos="0")
        self.assertEqual(gratis.margen, Decimal("0"))
        resumen = resumen_financiero()
        self.assertEqual(resumen["precios_pendientes"], 1)
        self.assertEqual(resumen["visitas_completas"], 1)
        self.assertEqual(resumen["saldo"], Decimal("10000"))

    def test_margen_y_saldo_negativos_permitidos(self):
        visita = self.visita(precio_cobrado="50", costo_materiales="80")
        self.pago(datos_pago(importe="11000"))
        self.assertEqual(visita.margen, Decimal("-30"))
        self.assertEqual(resumen_financiero()["saldo"], Decimal("-950"))

    def test_importes_decimales_exactos(self):
        self.pago(datos_pago(importe="0.10"))
        self.visita(precio_cobrado="0.30", costo_materiales="0.10", otros_gastos="0.10", gastos_pagados_en_visita=True)
        self.assertEqual(resumen_financiero()["saldo"], Decimal("10000.00"))

    def test_visitas_y_gastos_anteriores_no_cambian_saldo(self):
        ayer = timezone.localdate() - timedelta(days=1)
        self.pago(datos_pago(fecha=ayer))
        self.visita(fecha=ayer, gastos_pagados_en_visita=True)
        self.visita()
        self.assertEqual(resumen_financiero()["saldo"], Decimal("10500"))
        self.client.force_login(self.actor)
        pagina = self.client.get(reverse("finanzas:inicio"), {"historial": "1"})
        self.assertContains(pagina, "Anterior al período")
        self.assertContains(pagina, "Luz semanal")

    def test_doble_envio_gasto_idempotente_y_reutilizacion_rechazada(self):
        datos = datos_pago()
        self.assertEqual(self.pago(datos).pk, self.pago(datos).pk)
        self.assertEqual(resumen_financiero()["saldo"], Decimal("9800"))
        with self.assertRaises(ValidationError):
            self.pago({**datos, "importe": "201"})
        self.assertEqual(Gasto.objects.count(), 1)

    def test_anulacion_conserva_gasto_y_es_idempotente(self):
        pago = self.pago()
        anular_gasto(actor=self.actor, gasto_id=pago.pk, datos={"version": 1, "motivo": "Pago duplicado"})
        anular_gasto(actor=self.actor, gasto_id=pago.pk, datos={"version": 1, "motivo": "Pago duplicado"})
        self.assertEqual(resumen_financiero()["saldo"], Decimal("10000"))
        self.assertEqual(Gasto.objects.count(), 1)
        self.assertEqual(EventoAuditoria.objects.filter(operacion="gasto.anulado").count(), 1)

    def test_editar_gasto_con_control_version_y_auditoria(self):
        pago = self.pago()
        datos = datos_pago(importe="250", clave_operacion=pago.clave_operacion)
        self.pago(datos, gasto_id=pago.pk)
        self.assertEqual(resumen_financiero()["saldo"], Decimal("9750"))
        with self.assertRaises(ValidationError):
            self.pago(datos, gasto_id=pago.pk)
        with self.assertRaises(ValidationError):
            anular_gasto(actor=self.actor, gasto_id=pago.pk, datos={"version": 1, "motivo": "Error"})
        evento = EventoAuditoria.objects.get(operacion="gasto.editado")
        self.assertEqual(evento.cambios["antes"]["importe"], "200.00")
        self.assertEqual(evento.cambios["despues"]["importe"], "250")

    def test_errores_no_registran_gastos(self):
        for cambios in ({"importe": "0"}, {"importe": "-1"}, {"importe": "NaN"}, {"importe": "0.001"}, {"fecha": timezone.localdate()+timedelta(days=1)}, {"concepto": ""}, {"categoria": "inventada"}):
            with self.subTest(cambios=cambios), self.assertRaises(ValidationError):
                self.pago(datos_pago(**cambios))
        self.assertFalse(Gasto.objects.exists())

    def test_no_descontar_gasto_desconocido_ni_permitir_costos_negativos(self):
        for cambios in ({"costo_materiales": "-1"}, {"otros_gastos": "-1"}, {"gastos_pagados_en_visita": True, "costo_materiales": None}):
            with self.assertRaises(ValidationError):
                self.visita(**cambios)
        self.assertFalse(Atencion.objects.exists())

    def test_actualizar_base_conserva_registros_y_valida_version(self):
        self.pago()
        datos = {"saldo_inicial": "12000", "fecha_inicio": timezone.localdate(), "version": self.base.version}
        guardar_base(actor=self.actor, datos=datos)
        self.assertEqual(resumen_financiero()["saldo"], Decimal("11800"))
        self.assertEqual(Gasto.objects.count(), 1)
        with self.assertRaises(ValidationError):
            guardar_base(actor=self.actor, datos=datos)

    def test_base_invalida_no_cambia_saldo(self):
        for cambios in ({"saldo_inicial": "-1"}, {"fecha_inicio": timezone.localdate()+timedelta(days=1)}):
            with self.assertRaises(ValidationError):
                guardar_base(actor=self.actor, datos={"saldo_inicial": "10000", "fecha_inicio": timezone.localdate(), "version": 1, **cambios})
        self.assertEqual(resumen_financiero()["saldo"], Decimal("10000"))

    def test_rollback_si_falla_auditoria(self):
        with patch.object(EventoAuditoria.objects, "create", side_effect=RuntimeError("Prueba")):
            with self.assertRaises(RuntimeError):
                self.pago()
        self.assertFalse(Gasto.objects.exists())

    def test_permisos_servicios_y_paginas(self):
        actor = get_user_model().objects.create_user(username="sinpermiso")
        self.client.force_login(actor)
        for nombre in ("inicio", "base", "nuevo_gasto"):
            self.assertEqual(self.client.get(reverse("finanzas:"+nombre)).status_code, 403)
        for accion in (lambda: guardar_gasto(actor=actor, datos=datos_pago()), lambda: guardar_base(actor=actor, datos={})):
            with self.assertRaises(PermissionDenied):
                accion()
        self.client.logout()
        self.assertEqual(self.client.get(reverse("finanzas:inicio")).status_code, 302)

    def test_formularios_requieren_csrf_y_anular_get_no_muta(self):
        navegador = Client(enforce_csrf_checks=True)
        navegador.force_login(self.actor)
        pago = self.pago()
        url = reverse("finanzas:anular_gasto", args=[pago.pk])
        self.assertEqual(navegador.get(url).status_code, 200)
        pago.refresh_from_db()
        self.assertIsNone(pago.anulado_en)
        self.assertEqual(navegador.post(url, {"version": 1, "motivo": "Error"}).status_code, 403)
        token = navegador.cookies["csrftoken"].value
        self.assertEqual(navegador.post(url, {"version": 1, "motivo": "Error", "csrfmiddlewaretoken": token}).status_code, 302)
        self.assertEqual(navegador.post(reverse("finanzas:nuevo_gasto"), datos_pago()).status_code, 403)

    def test_paginas_muestran_importes_y_edicion_conserva_costos(self):
        visita = self.visita(otros_gastos="20")
        self.client.force_login(self.actor)
        for url in (reverse("finanzas:inicio"), reverse("atenciones:detalle", args=[visita.pk])):
            pagina = self.client.get(url)
            self.assertContains(pagina, "Costos" if "atenciones" in url else "Finanzas")
            self.assertContains(pagina, "400")
        pagina = self.client.get(reverse("atenciones:editar", args=[visita.pk]))
        self.assertEqual(pagina.context["form"].initial["costo_materiales"], Decimal("80"))
        self.assertEqual(pagina.context["form"].initial["otros_gastos"], Decimal("20"))
        self.assertContains(self.client.get(reverse("core:inicio")), 'href="/finanzas/"')

    def test_compatibilidad_huella_visita_anterior_sin_costos(self):
        from apps.inventario.services import huella
        from apps.atenciones.services import validar_datos
        datos = datos_visita()
        limpios = validar_datos(datos)
        anteriores = {k: v for k, v in limpios.items() if k not in ("version", "costo_materiales", "otros_gastos", "gastos_pagados_en_visita")}
        visita = guardar_atencion(actor=self.actor, datos=datos)
        self.assertEqual(visita.huella_operacion, huella(anteriores | {"actor": self.actor.pk}))

    @override_settings(OPENAI_API_KEY="solo-para-pruebas")
    def test_ia_separa_importes_sin_guardar_y_no_activa_pago_por_inferencia(self):
        conv = Conversacion.objects.create(usuario=self.actor, sesion="finanzas-prueba")
        args = {k: v for k, v in datos_visita(costo_materiales="80", otros_gastos="20", gastos_pagados_en_visita=True).items() if k not in ("version", "clave_operacion")}
        args["avisos"] = []
        api = MagicMock()
        api.responses.create.return_value = llamada("preparar_atencion", args)
        conversar(conversacion=conv, texto="Cobré 500, materiales 80 y otros gastos 20", formulario={"gastos_pagados_en_visita": False}, cliente_api=api)
        borrador = Borrador.objects.get()
        self.assertEqual(borrador.datos["precio_cobrado"], "500")
        self.assertEqual(borrador.datos["costo_materiales"], "80")
        self.assertEqual(borrador.datos["otros_gastos"], "20")
        self.assertFalse(borrador.datos["gastos_pagados_en_visita"])
        self.assertFalse(Atencion.objects.exists())
        self.assertFalse(Gasto.objects.exists())

    @override_settings(OPENAI_API_KEY="solo-para-pruebas")
    def test_ia_conserva_casilla_humana_y_costos_desconocidos_son_null(self):
        conv = Conversacion.objects.create(usuario=self.actor, sesion="finanzas-prueba")
        args = {k: v for k, v in datos_visita(costo_materiales="80", otros_gastos="0").items() if k not in ("version", "clave_operacion")}
        args["avisos"] = []
        api = MagicMock()
        api.responses.create.return_value = llamada("preparar_atencion", args)
        conversar(conversacion=conv, texto="Cobré 500", formulario={"gastos_pagados_en_visita": True, "costo_materiales": "80", "otros_gastos": "0"}, cliente_api=api)
        self.assertTrue(Borrador.objects.get().datos["gastos_pagados_en_visita"])
        esquema = next(t for t in TOOLS if t["name"] == "preparar_atencion")["parameters"]
        self.assertEqual(set(esquema["required"]), set(esquema["properties"]))
        args["costo_materiales"] = None
        validar_argumentos("preparar_atencion", args)
        for valor in ("-1", "NaN", "80 pesos", "1,50"):
            with self.assertRaises(ValidationError):
                validar_argumentos("preparar_atencion", {**args, "otros_gastos": valor})


class GastosConcurrentesTests(TransactionTestCase):
    def test_envios_simultaneos_no_duplican_gasto(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections

        ConfiguracionSalon.objects.get_or_create(pk=1)
        actor = get_user_model().objects.create_superuser(username="Finanzas", password="SoloParaPruebas123!")
        datos = datos_pago()
        barrera = Barrier(2)

        def enviar(_):
            close_old_connections()
            try:
                usuario = get_user_model().objects.get(pk=actor.pk)
                barrera.wait(timeout=10)
                return guardar_gasto(actor=usuario, datos=datos).pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(enviar, range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(Gasto.objects.count(), 1)
