from datetime import datetime, time
import json
import logging
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

from django.conf import settings
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
import requests

from .crypto import ConflictoGoogle, ErrorGoogle, cifrar, descifrar
from .models import ConexionGoogle

logger = logging.getLogger(__name__)


def causa_error(response):
    """Extrae solo códigos conocidos; no conserva mensajes ni datos de Google."""
    try:
        error = response.json().get("error", {})
        if not isinstance(error, dict):
            return "desconocida"
        razones = {
            detalle.get("reason") for campo in ("errors", "details")
            for detalle in error.get(campo, []) if isinstance(detalle, dict)
            and isinstance(detalle.get("reason"), str)
        }
    except (ValueError, TypeError, AttributeError):
        return "desconocida"
    if razones & {"SERVICE_DISABLED", "API_DISABLED", "accessNotConfigured"}:
        return "api_no_habilitada"
    if razones & {"ACCESS_TOKEN_SCOPE_INSUFFICIENT", "insufficientPermissions"}:
        return "permisos_insuficientes"
    if razones & {"RATE_LIMIT_EXCEEDED", "QUOTA_EXCEEDED", "userRateLimitExceeded", "rateLimitExceeded", "quotaExceeded", "dailyLimitExceeded"}:
        return "limite_temporal"
    return "desconocida"


class RespuestaGoogle(ErrorGoogle):
    def __init__(self, status):
        self.status = status
        super().__init__("Google no pudo completar la operación. Puedes reintentar desde la cita.")


class GoogleCalendar:
    def __init__(self, conexion=None, credentials=None):
        self.conexion = conexion
        if credentials is None:
            credentials = Credentials.from_authorized_user_info(json.loads(descifrar(conexion.credenciales_cifradas)))
        self.credentials = credentials
        self.session = AuthorizedSession(credentials, refresh_timeout=settings.GOOGLE_HTTP_TIMEOUT)

    def close(self):
        self.session.close()

    def request(self, method, path, *, params=None, data=None, etag=None, permitidos=()):
        headers = {"If-Match": etag} if etag else {}
        try:
            response = self.session.request(method, "https://www.googleapis.com/calendar/v3/" + path, params=params, json=data, headers=headers, timeout=settings.GOOGLE_HTTP_TIMEOUT)
            if self.conexion:
                ConexionGoogle.objects.filter(pk=self.conexion.pk).update(credenciales_cifradas=cifrar(self.credentials.to_json()))
        except RefreshError:
            if self.conexion:
                ConexionGoogle.objects.filter(pk=self.conexion.pk).update(requiere_autorizacion=True)
            raise ErrorGoogle("Google necesita una nueva autorización. Reconecta la cuenta.") from None
        except (requests.RequestException, TransportError):
            raise ErrorGoogle("No pudimos comunicarnos con Google. La cita sigue guardada en el salón.") from None
        if response.status_code in (401, 403, 429):
            causa = causa_error(response)
            logger.warning("Calendar: HTTP %s; causa=%s", response.status_code, causa)
            if response.status_code == 401:
                if self.conexion:
                    ConexionGoogle.objects.filter(pk=self.conexion.pk).update(requiere_autorizacion=True)
                raise ErrorGoogle("Google necesita una nueva autorización. Reconecta la cuenta.", codigo="autorizacion_vencida")
            if response.status_code == 403 and causa == "api_no_habilitada":
                raise ErrorGoogle("Google Calendar API no está habilitada en el proyecto. En Google Cloud, abre APIs y servicios → Biblioteca → Google Calendar API y pulsa Habilitar. Después vuelve a conectar la cuenta.", codigo=causa)
            if response.status_code == 403 and causa == "permisos_insuficientes":
                if self.conexion:
                    ConexionGoogle.objects.filter(pk=self.conexion.pk).update(requiere_autorizacion=True)
                raise ErrorGoogle("Faltan permisos de calendario. Reconecta la cuenta y acepta los permisos solicitados.", codigo=causa)
            if response.status_code == 429 or causa == "limite_temporal":
                raise ErrorGoogle("Google alcanzó un límite temporal de solicitudes. Espera unos minutos y vuelve a intentar; no necesitas reconectar la cuenta.", codigo="limite_temporal")
            raise ErrorGoogle("Google no autorizó la operación. Revisa los permisos o reconecta la cuenta.")
        if response.status_code == 412:
            raise ConflictoGoogle("El evento cambió en Google. Revisa ambas versiones antes de continuar.")
        if response.status_code >= 400 and response.status_code not in permitidos:
            raise RespuestaGoogle(response.status_code)
        try:
            content = response.json() if response.content else {}
        except ValueError:
            raise ErrorGoogle("Google devolvió una respuesta inesperada. Reintenta más tarde.") from None
        return response.status_code, content

    def calendarios(self):
        result, page = [], None
        for _ in range(20):
            _, data = self.request("GET", "users/me/calendarList", params={"maxResults": 250, "pageToken": page})
            result.extend(c for c in data.get("items", []) if c.get("accessRole") == "owner")
            page = data.get("nextPageToken")
            if not page:
                return result
        raise ErrorGoogle("Hay demasiados calendarios para listarlos. Revisa la cuenta conectada.")

    def evento_path(self, calendario_id, evento_id=None):
        path = "calendars/" + quote(calendario_id, safe="") + "/events"
        return path + "/" + quote(evento_id, safe="") if evento_id else path

    def obtener_evento(self, calendario_id, evento_id):
        status, event = self.request("GET", self.evento_path(calendario_id, evento_id), permitidos=(404, 410))
        return event if status == 200 else None

    def publicar(self, calendario_id, event, etag=None):
        if etag:
            return self.request("PUT", self.evento_path(calendario_id, event["id"]), data=event, etag=etag, params={"sendUpdates": "none"})[1]
        status, result = self.request("POST", self.evento_path(calendario_id), data=event, params={"sendUpdates": "none"}, permitidos=(409,))
        if status == 409:
            return None
        return result

    def cancelar(self, calendario_id, evento_id, etag):
        self.request("DELETE", self.evento_path(calendario_id, evento_id), etag=etag, params={"sendUpdates": "none"}, permitidos=(404, 410))

    def eventos(self, inicio, fin, *, zona="America/Merida"):
        """Consulta eventos del calendario elegido, sin crear registros locales."""
        params = {
            "timeMin": inicio.isoformat(), "timeMax": fin.isoformat(), "timeZone": zona,
            "singleEvents": "true", "showDeleted": "false", "orderBy": "startTime",
            "maxResults": 250, "fields": "timeZone,nextPageToken,items(id,summary,start,end,status,htmlLink)",
        }
        resultado = []
        for _ in range(10):
            _, data = self.request("GET", self.evento_path(self.conexion.calendario_id), params=params)
            if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
                raise ErrorGoogle("Google devolvió una lista de eventos inesperada. Vuelve a intentar.")
            for event in data.get("items", []):
                if not isinstance(event, dict):
                    raise ErrorGoogle("Google devolvió un evento inesperado. Vuelve a intentar.")
                if event.get("status") == "cancelled":
                    continue
                try:
                    def horario(parte):
                        if "dateTime" in parte:
                            valor = datetime.fromisoformat(parte["dateTime"].replace("Z", "+00:00"))
                            if valor.tzinfo is None:
                                valor = valor.replace(tzinfo=ZoneInfo(parte["timeZone"]))
                            return valor
                        return datetime.combine(datetime.fromisoformat(parte["date"]).date(), time.min, tzinfo=ZoneInfo(zona))
                    desde, hasta = horario(event["start"]), horario(event["end"])
                    if hasta <= desde or bool(event["start"].get("date")) != bool(event["end"].get("date")):
                        raise ValueError
                    url = event.get("htmlLink", "")
                    enlace = urlsplit(url)
                    seguro = enlace.scheme == "https" and not enlace.username and not enlace.password and enlace.port in (None, 443) and (
                        enlace.hostname == "calendar.google.com" or (enlace.hostname == "www.google.com" and enlace.path.startswith("/calendar/"))
                    )
                    if desde < fin and hasta > inicio:
                        resultado.append({"id": event["id"], "titulo": event.get("summary") or "Evento sin título", "inicio": desde, "fin": hasta, "todo_el_dia": "date" in event["start"], "url": url if seguro else ""})
                except (KeyError, ValueError, TypeError, AttributeError):
                    raise ErrorGoogle("No pudimos interpretar el horario de un evento de Google. Revisa el calendario y vuelve a intentar.") from None
            if not data.get("nextPageToken"):
                return resultado
            params["pageToken"] = data["nextPageToken"]
        raise ErrorGoogle("Hay demasiados eventos de Google en este periodo. Elige la vista de día para consultarlos.")

    def ocupaciones(self, inicio, fin, *, excluir_evento=None, zona="America/Merida"):
        result = []
        calendario = self.conexion.calendario_id
        params = {"timeMin": inicio.isoformat(), "timeMax": fin.isoformat(), "singleEvents": "true", "maxResults": 2500}
        for _ in range(10):
            _, data = self.request("GET", self.evento_path(calendario), params=params)
            for event in data.get("items", []):
                if event.get("id") == excluir_evento or event.get("status") == "cancelled" or event.get("transparency") == "transparent":
                    continue
                def horario(part):
                    if "dateTime" in part:
                        return datetime.fromisoformat(part["dateTime"].replace("Z", "+00:00"))
                    return datetime.combine(datetime.fromisoformat(part["date"]).date(), time.min, tzinfo=ZoneInfo(part.get("timeZone", zona)))
                result.append({"inicio": horario(event["start"]).isoformat(), "fin": horario(event["end"]).isoformat()})
            if not data.get("nextPageToken"):
                break
            params["pageToken"] = data["nextPageToken"]
        else:
            raise ErrorGoogle("No pudimos comprobar todas las ocupaciones del calendario.")
        # El calendario personal solo aporta horas ocupadas, sin nombres ni notas.
        if self.conexion.cuenta and self.conexion.cuenta != calendario:
            _, data = self.request("POST", "freeBusy", data={"timeMin": inicio.isoformat(), "timeMax": fin.isoformat(), "items": [{"id": self.conexion.cuenta}]})
            personal = data.get("calendars", {}).get(self.conexion.cuenta)
            if personal is None or personal.get("errors"):
                raise ErrorGoogle("No pudimos comprobar las ocupaciones del calendario personal.")
            result.extend({"inicio": b["start"], "fin": b["end"]} for b in personal.get("busy", []))
        return sorted(result, key=lambda value: (value["inicio"], value["fin"]))
