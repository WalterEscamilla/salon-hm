import struct
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class PwaTests(TestCase):
    def test_manifest_publico_sin_consultar_datos_privados(self):
        with self.assertNumQueries(0):
            respuesta = self.client.get(reverse("core:manifest"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta["Content-Type"], "application/manifest+json")
        datos = respuesta.json()
        self.assertEqual(datos["name"], "Salón HM")
        self.assertEqual(datos["id"], "/")
        self.assertEqual(datos["scope"], "/")
        self.assertEqual(datos["start_url"], reverse("core:inicio"))
        self.assertEqual(datos["display"], "standalone")
        self.assertFalse(datos["prefer_related_applications"])
        self.assertEqual({i["sizes"] for i in datos["icons"]}, {"192x192", "512x512"})
        self.assertTrue(any(i["purpose"] == "maskable" for i in datos["icons"]))
        self.assertNotIn("Set-Cookie", respuesta.headers)

    def test_pngs_reales_con_tamanos_correctos(self):
        iconos = self.client.get(reverse("core:manifest")).json()["icons"]
        for icono in iconos:
            ruta = Path(settings.BASE_DIR) / "static" / icono["src"].removeprefix("/static/")
            datos = ruta.read_bytes()
            self.assertEqual(datos[:8], b"\x89PNG\r\n\x1a\n")
            ancho, alto = struct.unpack(">II", datos[16:24])
            self.assertEqual(f"{ancho}x{alto}", icono["sizes"])
            self.assertEqual(icono["type"], "image/png")

    def test_worker_publico_con_alcance_raiz_y_actualizaciones_sin_cache_http(self):
        with self.assertNumQueries(0):
            respuesta = self.client.get(reverse("core:service_worker"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta["Cache-Control"], "no-cache")
        self.assertEqual(respuesta["Service-Worker-Allowed"], "/")
        self.assertIn("text/javascript", respuesta["Content-Type"])
        self.assertEqual(respuesta["X-Content-Type-Options"], "nosniff")
        self.assertContains(respuesta, reverse("core:offline"))
        self.assertNotContains(respuesta, "{%")

    def test_offline_publico_autosuficiente_sin_tokens_ni_datos_de_usuario(self):
        with self.assertNumQueries(0):
            anonima = self.client.get(reverse("core:offline"))
        self.assertContains(anonima, "Sin conexión")
        self.assertNotContains(anonima, "csrfmiddlewaretoken")
        self.assertNotContains(anonima, 'src="/static/')
        actor = get_user_model().objects.create_user(username="DatoPrivadoNoPublicar")
        self.client.force_login(actor)
        autenticada = self.client.get(reverse("core:offline"))
        self.assertEqual(anonima.content, autenticada.content)
        self.assertNotContains(autenticada, actor.username)

    def test_recursos_pwa_no_habilitan_escrituras_ni_paginas_privadas(self):
        for nombre in ("manifest", "service_worker", "offline"):
            with self.subTest(nombre=nombre):
                self.assertEqual(self.client.post(reverse("core:"+nombre)).status_code, 405)
        for url in (reverse("core:inicio"), reverse("finanzas:inicio"), reverse("clientes:listado")):
            respuesta = self.client.get(url)
            self.assertEqual(respuesta.status_code, 302)
            self.assertIn("/cuenta/entrar/", respuesta.url)

    def test_login_contiene_manifest_instalacion_y_worker_sin_instalar_automaticamente(self):
        respuesta = self.client.get(reverse("cuentas:login"))
        self.assertContains(respuesta, f'href="{reverse("core:manifest")}"')
        self.assertContains(respuesta, f'data-service-worker="{reverse("core:service_worker")}"')
        self.assertContains(respuesta, 'id="pwa-install-button"')
        self.assertContains(respuesta, 'id="pwa-install"')
        self.assertContains(respuesta, "Instalar app")
