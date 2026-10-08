from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class ErrorGoogle(Exception):
    def __init__(self, mensaje, *, codigo=""):
        super().__init__(mensaje)
        self.codigo = codigo


class ConflictoGoogle(ErrorGoogle):
    pass


def cifrador():
    try:
        return Fernet(settings.GOOGLE_TOKEN_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError):
        raise ErrorGoogle("Falta configurar la clave de cifrado para conectar Google.") from None


def cifrar(texto):
    return cifrador().encrypt(texto.encode()).decode()


def descifrar(texto):
    try:
        return cifrador().decrypt(texto.encode()).decode()
    except InvalidToken:
        raise ErrorGoogle("No se puede leer la conexión guardada. Revisa la clave de cifrado o reconecta Google.") from None
