import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.auditoria.models import EventoAuditoria
from apps.integraciones.models import ConexionGoogle


@override_settings(
    GOOGLE_CLIENT_ID="cliente-prueba.apps.googleusercontent.com",
    GOOGLE_CLIENT_SECRET="secreto-prueba",
    GOOGLE_LOGIN_EMAIL="marisol@example.invalid",
    GOOGLE_LOGIN_USERNAME="Marisol",
    GOOGLE_REDIRECT_URI="http://127.0.0.1:8010/calendario/google/retorno/",
)
class GoogleAccesoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(username="Marisol", password="ClaveSoloParaPruebas123!", first_name="Marisol")

    def inicio(self, client=None):
        client = client or self.client
        respuesta = client.post(reverse("cuentas:google_login"))
        self.assertEqual(respuesta.status_code, 302)
        return client.session["google_login"]

    def callback(self, *, claims=None, client=None, state=None):
        client = client or self.client
        context = client.session["google_login"]
        datos = {"sub": "identidad-google-prueba", "email": "marisol@example.invalid", "email_verified": True, "nonce": context["nonce"]}
        datos.update(claims or {})
        with patch("apps.cuentas.google.crear_flow") as flow, patch("apps.cuentas.google.verificar_token", return_value=datos) as verificar:
            flow.return_value.oauth2session.token = {"id_token": "token-ficticio"}
            response = client.get(reverse("integraciones:retorno"), {"state": state or context["state"], "code": "codigo-ficticio"})
        return response, flow, verificar

    def sin_acceso(self):
        self.assertNotIn("_auth_user_id", self.client.session)
        self.usuario.refresh_from_db()
        self.assertIsNone(self.usuario.google_sub)
        self.assertEqual(self.usuario.email, "")
        self.assertFalse(EventoAuditoria.objects.filter(operacion="google.login").exists())

    def test_boton_publico_sin_exponer_secretos(self):
        response = self.client.get(reverse("cuentas:login"))
        self.assertContains(response, "Entrar con Google")
        self.assertNotContains(response, "secreto-prueba")

    @override_settings(GOOGLE_CLIENT_SECRET="")
    def test_sin_configuracion_no_se_muestra_boton(self):
        self.assertNotContains(self.client.get(reverse("cuentas:login")), "Entrar con Google")
        self.assertRedirects(self.client.post(reverse("cuentas:google_login")), reverse("cuentas:login"))

    def test_inicio_requiere_post_y_csrf(self):
        self.assertEqual(self.client.get(reverse("cuentas:google_login")).status_code, 405)
        estricto = Client(enforce_csrf_checks=True)
        self.assertEqual(estricto.post(reverse("cuentas:google_login")).status_code, 403)
        estricto.get(reverse("cuentas:login"))
        response = estricto.post(reverse("cuentas:google_login"), HTTP_X_CSRFTOKEN=estricto.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 302)

    def test_solicitud_real_pkce_nonce_solo_identidad(self):
        response = self.client.post(reverse("cuentas:google_login"))
        partes = urlsplit(response.url)
        query = parse_qs(partes.query)
        context = self.client.session["google_login"]
        self.assertEqual(partes.hostname, "accounts.google.com")
        self.assertEqual(set(query["scope"][0].split()), {"openid", "https://www.googleapis.com/auth/userinfo.email"})
        self.assertEqual(query["nonce"][0], context["nonce"])
        self.assertEqual(query["state"][0], context["state"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertTrue(context["verifier"])
        self.assertEqual(query["redirect_uri"], ["http://127.0.0.1:8010/calendario/google/retorno/"])
        self.assertEqual(query["include_granted_scopes"], ["false"])

    def test_entrada_verificada_vincula_usuario_existente_y_rota_sesion(self):
        self.inicio()
        antes = self.client.session.session_key
        response, flow, verificar = self.callback()
        self.assertRedirects(response, reverse("core:inicio"))
        self.assertEqual(self.client.session["_auth_user_id"], str(self.usuario.pk))
        self.assertNotEqual(antes, self.client.session.session_key)
        self.assertNotIn("google_login", self.client.session)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.google_sub, "identidad-google-prueba")
        self.assertEqual(self.usuario.email, "marisol@example.invalid")
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertFalse(ConexionGoogle.objects.exists())
        self.assertEqual(EventoAuditoria.objects.filter(operacion="google.login").count(), 1)
        verificar.assert_called_once_with("token-ficticio")
        flow.return_value.fetch_token.assert_called_once_with(code="codigo-ficticio", timeout=10)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    def test_otro_correo_se_rechaza(self):
        self.inicio()
        response, _, _ = self.callback(claims={"email": "otra@example.invalid"})
        self.assertRedirects(response, reverse("cuentas:login"))
        self.sin_acceso()

    def test_claims_invalidos_se_rechazan(self):
        for claims in [{"email_verified": False}, {"email_verified": "true"}, {"nonce": "otra"}, {"nonce": None}, {"sub": ""}, {"azp": "otro-cliente"}]:
            with self.subTest(claims=claims):
                self.inicio()
                self.callback(claims=claims)
                self.sin_acceso()

    def test_state_incorrecto_no_contacta_google(self):
        self.inicio()
        _, flow, verificar = self.callback(state="incorrecto")
        flow.assert_not_called()
        verificar.assert_not_called()
        self.sin_acceso()

    def test_autorizacion_caducada_o_fecha_futura_no_contacta_google(self):
        for desplazamiento in [-601, 60]:
            self.inicio()
            session = self.client.session
            session["google_login"]["creado"] = time.time() + desplazamiento
            session.save()
            _, flow, _ = self.callback()
            flow.assert_not_called()
            self.sin_acceso()

    def test_token_rechazado_por_verificador_no_da_acceso(self):
        self.inicio()
        context = self.client.session["google_login"]
        with patch("apps.cuentas.google.crear_flow") as flow, patch("apps.cuentas.google.verificar_token", side_effect=ValueError("firma o audiencia invalida")):
            flow.return_value.oauth2session.token = {"id_token": "token-ficticio"}
            self.client.get(reverse("integraciones:retorno"), {"state": context["state"], "code": "codigo-ficticio"})
        self.sin_acceso()

    def test_biblioteca_recibe_audiencia_y_peticion_con_timeout(self):
        from .google import verificar_token
        with patch("apps.cuentas.google.Request") as request, patch("apps.cuentas.google.id_token.verify_oauth2_token") as verificar:
            verificar.side_effect = lambda token, fetch, audience: fetch("https://certificados.example.invalid")
            verificar_token("token")
        self.assertEqual(verificar.call_args.kwargs["audience"], "cliente-prueba.apps.googleusercontent.com")
        request.return_value.assert_called_once_with("https://certificados.example.invalid", timeout=10)

    def test_cancelacion_consume_state_sin_intercambiar_codigo(self):
        context = self.inicio()
        with patch("apps.cuentas.google.crear_flow") as flow:
            self.client.get(reverse("integraciones:retorno"), {"state": context["state"], "error": "access_denied"})
        flow.assert_not_called()
        self.assertNotIn("google_login", self.client.session)
        self.sin_acceso()

    def test_callback_no_se_reutiliza(self):
        context = self.inicio()
        self.callback()
        with patch("apps.cuentas.google.crear_flow") as flow:
            self.client.get(reverse("integraciones:retorno"), {"state": context["state"], "code": "codigo-ficticio"})
        flow.assert_not_called()
        self.assertEqual(EventoAuditoria.objects.filter(operacion="google.login").count(), 1)

    def test_sesion_distinta_no_puede_usar_callback(self):
        context = self.inicio()
        otra = Client()
        with patch("apps.cuentas.google.crear_flow") as flow:
            otra.get(reverse("integraciones:retorno"), {"state": context["state"], "code": "codigo-ficticio"})
        flow.assert_not_called()
        self.assertNotIn("_auth_user_id", otra.session)
        self.sin_acceso()

    def test_identidad_persistente_no_se_reemplaza_por_otro_sub(self):
        self.usuario.google_sub = "identidad-anterior"
        self.usuario.save(update_fields=["google_sub"])
        self.inicio()
        self.callback()
        self.assertNotIn("_auth_user_id", self.client.session)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.google_sub, "identidad-anterior")

    def test_usuario_inactivo_o_inexistente_no_se_crea(self):
        self.usuario.is_active = False
        self.usuario.save(update_fields=["is_active"])
        self.inicio()
        self.callback()
        self.sin_acceso()
        with override_settings(GOOGLE_LOGIN_USERNAME="NoExiste"):
            self.inicio()
            self.callback()
            self.sin_acceso()
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_fallo_auditoria_revierte_vinculacion(self):
        self.inicio()
        with patch("apps.cuentas.google.EventoAuditoria.objects.create", side_effect=RuntimeError("error")):
            self.callback()
        self.sin_acceso()

    def test_cambio_configuracion_invalida_autorizacion_pendiente(self):
        self.inicio()
        with override_settings(GOOGLE_LOGIN_EMAIL="otra@example.invalid"):
            _, flow, _ = self.callback()
        flow.assert_not_called()
        self.sin_acceso()

    def test_callback_calendar_sigue_privado_sin_flujo_login(self):
        response = self.client.get(reverse("integraciones:retorno"), {"state": "inventado", "code": "inventado"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("cuentas:login"), response.url)
        self.assertFalse(ConexionGoogle.objects.exists())

    def test_misma_identidad_no_puede_vincularse_a_dos_usuarios(self):
        get_user_model().objects.create_user(username="Otra", google_sub="identidad-google-prueba")
        self.inicio()
        self.callback()
        self.sin_acceso()

    def test_login_password_abandona_autorizacion_google_pendiente(self):
        self.inicio()
        self.client.post(reverse("cuentas:login"), {"username": "Marisol", "password": "ClaveSoloParaPruebas123!"})
        self.assertEqual(self.client.session["_auth_user_id"], str(self.usuario.pk))
        self.assertNotIn("google_login", self.client.session)

    def test_callback_pendiente_no_cambia_usuario_ya_autenticado(self):
        context = self.inicio()
        otro = get_user_model().objects.create_user(username="Walter")
        self.client.force_login(otro)
        with patch("apps.cuentas.google.completar") as completar:
            response = self.client.get(reverse("integraciones:retorno"), {"state": context["state"], "code": "codigo-ficticio"})
        self.assertRedirects(response, reverse("core:inicio"))
        completar.assert_not_called()
        self.assertEqual(self.client.session["_auth_user_id"], str(otro.pk))
        self.assertNotIn("google_login", self.client.session)
