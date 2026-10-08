from django.conf import settings
from google_auth_oauthlib.flow import Flow

from .crypto import ErrorGoogle, cifrador


def configurado():
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.GOOGLE_TOKEN_ENCRYPTION_KEY)


def crear_flow(*, state=None, verifier=None):
    if not configurado():
        raise ErrorGoogle("Completa las credenciales de Google en .env antes de conectar.")
    cifrador()
    return Flow.from_client_config(
        {"web": {"client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET, "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [settings.GOOGLE_REDIRECT_URI]}},
        scopes=settings.GOOGLE_OAUTH_SCOPES,
        redirect_uri=settings.GOOGLE_REDIRECT_URI,
        state=state,
        code_verifier=verifier,
        autogenerate_code_verifier=verifier is None,
    )

