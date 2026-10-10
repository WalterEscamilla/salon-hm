from decimal import Decimal
from unittest.mock import MagicMock, patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from apps.inventario.models import MovimientoStock, Producto
from apps.inventario.tests_initial_stock import datos_iniciales
from .messages import Error
from .models import Borrador, Conversacion
from .openai_service import TOOLS, conversar, ejecutar_herramienta
from .services import confirmar, editar_borrador, preparar, token_confirmacion
from .tests import llamada, respuesta


class InventarioAsistenteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="inventario-ia", password="SoloPruebas123!")

    def setUp(self):
        self.client.force_login(self.actor)
        self.conv = Conversacion.objects.create(usuario=self.actor, sesion=self.client.session.session_key)

    def propuesta(self, **extra):
        return preparar(conversacion=self.conv, tipo="producto", entidad_id=None, datos=datos_iniciales(**extra))

    def test_ia_interpreta_botellas_y_confirmacion_unica_registra_conteo(self):
        args = {"id": None, **datos_iniciales()}
        args.pop("clave_alta")
        args.update(presentacion=None, minimo_presentaciones=None)
        api = MagicMock()
        api.responses.create.side_effect = [llamada("preparar_producto", args), respuesta("Propuesta preparada.")]
        conversar(conversacion=self.conv, texto="Peróxido 30 vol, 875 ml por botella, 65 pesos, 3.5 botellas.", cliente_api=api)
        self.assertFalse(Producto.objects.exists())
        self.assertFalse(MovimientoStock.objects.exists())
        borrador = Borrador.objects.get()
        pagina = self.client.get(reverse("asistente:borrador", args=[borrador.pk]))
        self.assertContains(pagina, "Conteo inicial")
        self.assertEqual(pagina.context["stock_inicial"], Decimal("3062.5"))
        self.assertContains(pagina, 'name="cantidad_inicial"')
        token = token_confirmacion(borrador)
        url = confirmar(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, token=token)
        self.assertEqual(confirmar(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, token=token), url)
        self.assertEqual(Producto.objects.get().existencias, Decimal("3062.500"))
        self.assertEqual(MovimientoStock.objects.count(), 1)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_producto_del_chat_abre_propuesta_generada_por_el_servidor(self):
        def interpretar(**kwargs):
            preparar(conversacion=kwargs["conversacion"], tipo="producto", entidad_id=None, datos=datos_iniciales())
        with patch("apps.asistente.views.conversar", side_effect=interpretar):
            post = self.client.post(reverse("asistente:chat"), {"texto": "Producto con 3.5 botellas"})
        borrador = Borrador.objects.get()
        self.assertRedirects(post, reverse("asistente:borrador", args=[borrador.pk]))
        self.assertFalse(Producto.objects.exists())

    def test_editar_conteo_conserva_clave_y_exige_token_nuevo(self):
        borrador = self.propuesta()
        token = token_confirmacion(borrador)
        clave = borrador.datos["clave_alta"]
        datos = datos_iniciales(cantidad_inicial="4")
        editar_borrador(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, datos=datos, version=1)
        borrador.refresh_from_db()
        self.assertEqual(borrador.datos["clave_alta"], clave)
        with self.assertRaises(ValidationError):
            confirmar(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, token=token)
        confirmar(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, token=token_confirmacion(borrador))
        self.assertEqual(Producto.objects.get().existencias, Decimal("3500"))

    def test_borrador_antiguo_sin_campos_de_conteo_sigue_funcionando(self):
        borrador = self.propuesta(cantidad_inicial=None)
        for campo in ("cantidad_inicial", "modo_cantidad", "clave_alta"):
            borrador.datos.pop(campo, None)
        borrador.save(update_fields=["datos"])
        self.assertEqual(self.client.get(reverse("asistente:borrador", args=[borrador.pk])).status_code, 200)
        confirmar(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, token=token_confirmacion(borrador))
        self.assertEqual(Producto.objects.get().existencias, 0)
        self.assertFalse(MovimientoStock.objects.exists())

    def test_producto_existente_se_edita_sin_reiniciar_stock(self):
        borrador = self.propuesta()
        confirmar(borrador_id=borrador.pk, actor=self.actor, sesion=self.conv.sesion, token=token_confirmacion(borrador))
        producto = Producto.objects.get()
        args = {"id": producto.pk, "nombre": None, "presentacion": None, "marca": None, "descripcion": None, "unidad": None, "contenido_envase": None, "costo_envase": "70", "stock_minimo": None, "minimo_presentaciones": None, "activo": None, "cantidad_inicial": None, "modo_cantidad": None}
        ejecutar_herramienta(conversacion=self.conv, nombre="preparar_producto", args=args, observados={("producto", producto.pk)})
        editar = Borrador.objects.exclude(pk=borrador.pk).get()
        self.assertEqual(self.client.get(reverse("asistente:borrador", args=[editar.pk])).status_code, 200)
        confirmar(borrador_id=editar.pk, actor=self.actor, sesion=self.conv.sesion, token=token_confirmacion(editar))
        producto.refresh_from_db()
        self.assertEqual(producto.costo_envase, Decimal("70"))
        self.assertEqual(producto.existencias, Decimal("3062.500"))
        with self.assertRaises(ValidationError):
            ejecutar_herramienta(conversacion=self.conv, nombre="preparar_producto", args={**args, "cantidad_inicial": "4"}, observados={("producto", producto.pk)})

    def test_propuesta_inexistente_o_enlace_incorrecto_recupera_chat(self):
        for url in [reverse("asistente:borrador", args=[uuid.uuid4()]), "/asistente/borrador/enlace-inventado/"]:
            post = self.client.get(url, follow=True)
            self.assertContains(post, Error.ProposalUnavailable)
            self.assertEqual(post.redirect_chain[-1][0], reverse("asistente:chat"))
        self.assertFalse(Producto.objects.exists())

    def test_otra_sesion_y_otro_usuario_recuperan_chat_sin_ver_datos(self):
        borrador = self.propuesta(nombre="NombrePrivadoParaPrueba")
        otro = get_user_model().objects.create_superuser(username="otro-inventario", password="SoloPruebas123!")
        for actor in (self.actor, otro):
            navegador = Client()
            navegador.force_login(actor)
            pagina = navegador.get(reverse("asistente:borrador", args=[borrador.pk]), follow=True)
            self.assertContains(pagina, Error.ProposalUnavailable)
            self.assertNotContains(pagina, "NombrePrivadoParaPrueba")
        self.assertFalse(Producto.objects.exists())

    def test_datos_invalidos_se_muestran_en_formulario_y_no_escriben_stock(self):
        borrador = self.propuesta()
        post = self.client.post(reverse("asistente:borrador", args=[borrador.pk]), {"accion": "editar", "version_borrador": 1, **datos_iniciales(contenido_envase="")})
        self.assertContains(post, "Indica cuánto trae cada botella")
        self.assertEqual(post.context["form"]["cantidad_inicial"].value(), "3.5")
        self.assertFalse(Producto.objects.exists())
        self.assertFalse(MovimientoStock.objects.exists())

    def test_esquema_incluye_conteo_nullable_sin_herramienta_de_guardado(self):
        herramienta = next(tool for tool in TOOLS if tool["name"] == "preparar_producto")
        propiedades = herramienta["parameters"]["properties"]
        self.assertEqual(propiedades["cantidad_inicial"]["type"], ["string", "null"])
        self.assertEqual(set(propiedades["modo_cantidad"]["enum"]), {"base", "envases", None})
        self.assertCountEqual(herramienta["parameters"]["required"], propiedades)
        self.assertFalse(any(tool["name"].startswith("guardar") for tool in TOOLS))
