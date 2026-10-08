import secrets
import time

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils.crypto import constant_time_compare
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow

from apps.auditoria.models import EventoAuditoria


def configurado():
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.GOOGLE_LOGIN_EMAIL and settings.GOOGLE_LOGIN_USERNAME)


def crear_flow(*, state, verifier=None):
    if not configurado():
        raise ValueError("El acceso de Google no está configurado.")
    return Flow.from_client_config(
        {"web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }},
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"],
        redirect_uri=settings.GOOGLE_REDIRECT_URI,
        state=state,
        code_verifier=verifier,
        autogenerate_code_verifier=verifier is None,
    )


def iniciar(request):
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    flow = crear_flow(state=state)
    url, _ = flow.authorization_url(
        nonce=nonce, login_hint=settings.GOOGLE_LOGIN_EMAIL,
        prompt="select_account", access_type="online", include_granted_scopes="false",
    )
    # El retorno es compartido con Calendar; solo puede haber un flujo en curso.
    request.session.pop("google_oauth", None)
    request.session["google_login"] = {
        "state": state, "nonce": nonce, "verifier": flow.code_verifier,
        "creado": time.time(), "email": settings.GOOGLE_LOGIN_EMAIL,
        "username": settings.GOOGLE_LOGIN_USERNAME,
        "client_id": settings.GOOGLE_CLIENT_ID, "redirect_uri": settings.GOOGLE_REDIRECT_URI,
    }
    return url


def verificar_token(token):
    with requests.Session() as session:
        google_request = Request(session=session)

        def limitado(*args, **kwargs):
            kwargs["timeout"] = settings.GOOGLE_HTTP_TIMEOUT
            return google_request(*args, **kwargs)

        # La biblioteca verifica firma, audiencia, emisor y vencimiento.
        return id_token.verify_oauth2_token(token, limitado, audience=settings.GOOGLE_CLIENT_ID)


def completar(request):
    context = request.session.get("google_login", {})
    edad = time.time() - context.get("creado", 0)
    valido = (
        configurado() and 0 <= edad < 600 and bool(context.get("state"))
        and constant_time_compare(request.GET.get("state", ""), context.get("state", ""))
        and context.get("email") == settings.GOOGLE_LOGIN_EMAIL
        and context.get("username") == settings.GOOGLE_LOGIN_USERNAME
        and context.get("client_id") == settings.GOOGLE_CLIENT_ID
        and context.get("redirect_uri") == settings.GOOGLE_REDIRECT_URI
    )
    if not valido:
        raise ValueError("La autorización venció o no corresponde a tu sesión. Intenta de nuevo.")
    request.session.pop("google_login", None)
    if request.GET.get("error") or not request.GET.get("code"):
        raise ValueError("No se autorizó el acceso con Google. Puedes intentarlo de nuevo.")
    flow = crear_flow(state=context["state"], verifier=context["verifier"])
    flow.fetch_token(code=request.GET["code"], timeout=settings.GOOGLE_HTTP_TIMEOUT)
    token = flow.oauth2session.token.get("id_token")
    if not token:
        raise PermissionDenied
    claims = verificar_token(token)
    sub = claims.get("sub")
    if (
        not isinstance(sub, str) or not sub or len(sub) > 255
        or claims.get("email_verified") is not True
        or str(claims.get("email", "")).casefold() != settings.GOOGLE_LOGIN_EMAIL
        or not context.get("nonce") or not isinstance(claims.get("nonce"), str)
        or not constant_time_compare(claims["nonce"], context["nonce"])
        or claims.get("azp", settings.GOOGLE_CLIENT_ID) != settings.GOOGLE_CLIENT_ID
    ):
        raise PermissionDenied
    with transaction.atomic():
        usuario = get_user_model().objects.select_for_update().get(username=settings.GOOGLE_LOGIN_USERNAME, is_active=True)
        if usuario.google_sub and usuario.google_sub != sub:
            raise PermissionDenied
        if not usuario.google_sub:
            if get_user_model().objects.filter(google_sub=sub).exclude(pk=usuario.pk).exists():
                raise PermissionDenied
            usuario.google_sub = sub
        usuario.email = settings.GOOGLE_LOGIN_EMAIL
        usuario.save(update_fields=["google_sub", "email"])
        EventoAuditoria.objects.create(actor=usuario, origen="formulario", operacion="google.login", entidad="cuentas.Usuario", entidad_id=str(usuario.pk))
    return usuario
