from datetime import timedelta
from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.agenda.services import guardar_cita
from apps.asistente.models import Conversacion
from apps.asistente.openai_service import ejecutar_herramienta
from apps.asistente.services import confirmar, token_confirmacion
from apps.clientes.models import Cliente
from .forms import ServicioForm
from .models import Servicio
from .services import guardar_servicio


class CatalogoFlexibleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="Marisol", password="ClaveParaPruebas123!")

    def test_creacion_solo_nombre_sin_valores_inventados(self):
        servicio = guardar_servicio(actor=self.actor, datos={"nombre": "Maquillaje"})
        self.assertIsNone(servicio.precio_base)
        self.assertIsNone(servicio.duracion_minutos)
        self.assertTrue(servicio.activo)
        form = ServicioForm({"nombre": "Peinado", "activo": "on"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["precio_base"])
        self.assertIsNone(form.cleaned_data["duracion_minutos"])

    def test_referencias_opcionales_validan_cero_negativos_y_edicion_parcial(self):
        servicio = guardar_servicio(actor=self.actor, datos={"nombre": "Corte", "precio_base": Decimal("0"), "duracion_minutos": 45})
        servicio = guardar_servicio(actor=self.actor, servicio_id=servicio.pk, datos={"nombre": "Corte de dama"})
        self.assertEqual(servicio.precio_base, 0)
        self.assertEqual(servicio.duracion_minutos, 45)
        for cambios in ({"precio_base": Decimal("-1")}, {"duracion_minutos": 0}):
            with self.assertRaises(ValidationError):
                guardar_servicio(actor=self.actor, datos={"nombre": "Inválido", **cambios})

    def test_agendar_servicio_sin_duracion_respetando_horario_elegido(self):
        servicio = guardar_servicio(actor=self.actor, datos={"nombre": "Efectos de color"})
        cliente = Cliente.objects.create(nombre="Ana")
        inicio = timezone.now() + timedelta(days=1)
        cita = guardar_cita(actor=self.actor, sesion="prueba", datos={"cliente": cliente, "servicios": [servicio], "motivo": "", "inicio": inicio, "fin": inicio + timedelta(hours=3), "notas": "", "estado": "pendiente", "clave_operacion": uuid.uuid4()})
        self.assertIsNone(cita.servicios_previstos.get().duracion_minutos)
        self.assertEqual(cita.fin - cita.inicio, timedelta(hours=3))

    def test_asistente_prepara_catalogo_solo_nombre(self):
        from apps.asistente.models import Borrador
        conv = Conversacion.objects.create(usuario=self.actor, sesion="prueba-catalogo")
        ejecutar_herramienta(conversacion=conv, nombre="preparar_servicio", observados=set(), args={"id": None, "nombre": "Pedicure", "descripcion": None, "precio_base": None, "duracion_minutos": None, "activo": None})
        borrador = Borrador.objects.get()
        self.assertFalse(Servicio.objects.exists())
        confirmar(borrador_id=borrador.pk, actor=self.actor, sesion=conv.sesion, token=token_confirmacion(borrador))
        servicio = Servicio.objects.get()
        self.assertIsNone(servicio.precio_base)
        self.assertIsNone(servicio.duracion_minutos)

    def test_listado_muestra_precio_y_duracion_variables(self):
        guardar_servicio(actor=self.actor, datos={"nombre": "Tintes"})
        self.client.force_login(self.actor)
        response = self.client.get(reverse("catalogos:listado"))
        self.assertContains(response, "Precio según la clienta")
        self.assertContains(response, "Duración según la visita")
        self.assertNotContains(response, "$None")
