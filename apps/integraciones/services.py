from datetime import timedelta
import uuid

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.agenda.models import Cita

from .crypto import ConflictoGoogle, ErrorGoogle
from .google import GoogleCalendar
from .models import ConexionGoogle, TrabajoSincronizacion, VinculoEventoGoogle


def obtener_conexion(actor):
    return ConexionGoogle.objects.filter(usuario=actor, activa=True, requiere_autorizacion=False).exclude(calendario_id="").first()


def encolar_cita(cita, actor):
    conexion = obtener_conexion(actor)
    if not conexion:
        cita.sincronizacion = Cita.Sincronizacion.SIN_CONEXION
        cita.save(update_fields=["sincronizacion"])
        return None
    trabajo, _ = TrabajoSincronizacion.objects.get_or_create(cita=cita, conexion=conexion, version=cita.version, defaults={"proximo_intento": timezone.now()})
    cita.sincronizacion = {
        TrabajoSincronizacion.Estado.HECHO: Cita.Sincronizacion.SINCRONIZADA,
        TrabajoSincronizacion.Estado.ERROR: Cita.Sincronizacion.ERROR,
        TrabajoSincronizacion.Estado.CONFLICTO: Cita.Sincronizacion.CONFLICTO,
    }.get(trabajo.estado, Cita.Sincronizacion.PENDIENTE)
    cita.error_sincronizacion = trabajo.error
    cita.save(update_fields=["sincronizacion", "error_sincronizacion"])
    return trabajo


def payload_cita(cita, evento_id):
    # No incluye clientes, teléfono, servicios, notas, fórmulas ni costos.
    return {
        "id": evento_id,
        "summary": f"Salón HM · Cita {cita.pk}",
        "description": "Cita administrada desde Salón HM.",
        "start": {"dateTime": cita.inicio.isoformat()},
        "end": {"dateTime": cita.fin.isoformat()},
        "status": "tentative" if cita.estado == Cita.Estado.PENDIENTE else "confirmed",
        "reminders": {"useDefault": False},
        "extendedProperties": {"private": {"salon_hm_cita": str(cita.clave_operacion), "salon_hm_version": str(cita.version)}},
    }


def mismo_payload(evento, esperado):
    from datetime import datetime
    try:
        for campo in ("start", "end"):
            remoto = datetime.fromisoformat(evento[campo]["dateTime"].replace("Z", "+00:00"))
            local = datetime.fromisoformat(esperado[campo]["dateTime"])
            if remoto != local:
                return False
        return all(evento.get(c) == esperado[c] for c in ("summary", "description", "status")) and evento.get("extendedProperties", {}).get("private", {}) == esperado["extendedProperties"]["private"] and not evento.get("attendees") and not evento.get("reminders", {}).get("useDefault", False) and not evento.get("reminders", {}).get("overrides")
    except (KeyError, ValueError, TypeError):
        return False


def procesar_trabajo(trabajo_id):
    token = uuid.uuid4()
    ahora = timezone.now()
    with transaction.atomic():
        trabajo = TrabajoSincronizacion.objects.select_for_update().select_related("cita", "conexion").get(pk=trabajo_id)
        cita = Cita.objects.select_for_update().get(pk=trabajo.cita_id)
        if trabajo.estado in [TrabajoSincronizacion.Estado.HECHO, TrabajoSincronizacion.Estado.CONFLICTO, TrabajoSincronizacion.Estado.OBSOLETO]:
            return False
        if trabajo.estado == TrabajoSincronizacion.Estado.PROCESANDO and trabajo.bloqueo_hasta and trabajo.bloqueo_hasta > ahora:
            return False
        if trabajo.intentos >= 5 or trabajo.proximo_intento > ahora:
            return False
        if TrabajoSincronizacion.objects.filter(cita=cita, estado=TrabajoSincronizacion.Estado.PROCESANDO, bloqueo_hasta__gt=ahora).exclude(pk=trabajo.pk).exists():
            return False
        if cita.version != trabajo.version:
            trabajo.estado = TrabajoSincronizacion.Estado.OBSOLETO
            trabajo.save(update_fields=["estado"])
            return False
        conexion = trabajo.conexion
        if not conexion.activa or conexion.requiere_autorizacion or not conexion.calendario_id:
            return False
        trabajo.estado = TrabajoSincronizacion.Estado.PROCESANDO
        trabajo.intentos += 1
        trabajo.token_bloqueo = token
        trabajo.bloqueo_hasta = ahora + timedelta(seconds=90)
        trabajo.save()
        vinculo = VinculoEventoGoogle.objects.filter(cita=cita).first()
        if vinculo and (vinculo.conexion_id != conexion.pk or vinculo.calendario_id != conexion.calendario_id):
            trabajo.estado = TrabajoSincronizacion.Estado.CONFLICTO
            trabajo.error = "La cita pertenece a otro calendario. Revisa la conexión antes de publicar."
            trabajo.save()
            Cita.objects.filter(pk=cita.pk, version=trabajo.version).update(sincronizacion=Cita.Sincronizacion.CONFLICTO, error_sincronizacion=trabajo.error)
            return False
        if not vinculo and cita.estado != Cita.Estado.CANCELADA:
            vinculo = VinculoEventoGoogle.objects.create(cita=cita, conexion=conexion, calendario_id=conexion.calendario_id, evento_id="hm" + cita.clave_operacion.hex)
    estado, error, etag, cancelado = TrabajoSincronizacion.Estado.HECHO, "", None, False
    adapter = None
    try:
        if vinculo:
            adapter = GoogleCalendar(conexion)
            actual = adapter.obtener_evento(vinculo.calendario_id, vinculo.evento_id)
            if cita.estado == Cita.Estado.CANCELADA:
                if actual and actual.get("status") != "cancelled":
                    if not vinculo.etag or actual.get("etag") != vinculo.etag:
                        raise ConflictoGoogle("El evento cambió en Google. Revisa el cambio antes de cancelarlo.")
                    adapter.cancelar(vinculo.calendario_id, vinculo.evento_id, vinculo.etag)
                cancelado = True
            else:
                esperado = payload_cita(cita, vinculo.evento_id)
                if actual and actual.get("status") == "cancelled":
                    raise ConflictoGoogle("El evento fue eliminado en Google. La cita local se conserva.")
                if actual:
                    if trabajo.version > vinculo.version_sincronizada and mismo_payload(actual, esperado):
                        # Recupera una escritura exitosa cuya respuesta se perdió.
                        resultado = actual
                    elif not vinculo.etag or actual.get("etag") != vinculo.etag:
                        raise ConflictoGoogle("El evento cambió en Google. Revisa ambas versiones antes de publicar.")
                    else:
                        resultado = adapter.publicar(vinculo.calendario_id, esperado, etag=vinculo.etag)
                elif vinculo.version_sincronizada:
                    raise ConflictoGoogle("El evento fue eliminado en Google. La cita local se conserva.")
                else:
                    resultado = adapter.publicar(vinculo.calendario_id, esperado)
                    if resultado is None:
                        resultado = adapter.obtener_evento(vinculo.calendario_id, vinculo.evento_id)
                        if not resultado or not mismo_payload(resultado, esperado):
                            raise ConflictoGoogle("El identificador ya existe en Google con otros datos. No se sobrescribió.")
                etag = resultado.get("etag")
                if not etag:
                    raise ErrorGoogle("Google no devolvió la versión del evento. Reintenta para verificarlo.")
    except ConflictoGoogle as exc:
        estado, error = TrabajoSincronizacion.Estado.CONFLICTO, str(exc)
    except ErrorGoogle as exc:
        estado, error = TrabajoSincronizacion.Estado.ERROR, str(exc)
    except Exception:
        estado, error = TrabajoSincronizacion.Estado.ERROR, "No se pudo completar la sincronización. La cita local sigue guardada."
    finally:
        if adapter:
            adapter.close()
    with transaction.atomic():
        trabajo = TrabajoSincronizacion.objects.select_for_update().get(pk=trabajo_id)
        if trabajo.token_bloqueo != token:
            return False
        trabajo.estado = estado
        trabajo.error = error[:240]
        trabajo.bloqueo_hasta = None
        trabajo.proximo_intento = timezone.now() + timedelta(seconds=min(3600, 30 * 2 ** trabajo.intentos))
        trabajo.save()
        if vinculo and estado == TrabajoSincronizacion.Estado.HECHO:
            VinculoEventoGoogle.objects.filter(pk=vinculo.pk).update(etag=etag or vinculo.etag, version_sincronizada=trabajo.version, cancelado=cancelado)
        sincronizacion = {TrabajoSincronizacion.Estado.HECHO: Cita.Sincronizacion.SINCRONIZADA, TrabajoSincronizacion.Estado.CONFLICTO: Cita.Sincronizacion.CONFLICTO, TrabajoSincronizacion.Estado.ERROR: Cita.Sincronizacion.ERROR}[estado]
        Cita.objects.filter(pk=cita.pk, version=trabajo.version).update(sincronizacion=sincronizacion, error_sincronizacion=error[:240])
    return estado == TrabajoSincronizacion.Estado.HECHO


def sincronizar_cita(cita, actor):
    trabajo = TrabajoSincronizacion.objects.filter(cita=cita, conexion__usuario=actor, version=cita.version).first()
    if not trabajo:
        trabajo = encolar_cita(cita, actor)
    return procesar_trabajo(trabajo.pk) if trabajo else False


def trabajos_pendientes(limite=20):
    ahora = timezone.now()
    return TrabajoSincronizacion.objects.filter(Q(estado__in=[TrabajoSincronizacion.Estado.PENDIENTE, TrabajoSincronizacion.Estado.ERROR]) | Q(estado=TrabajoSincronizacion.Estado.PROCESANDO, bloqueo_hasta__lt=ahora), conexion__activa=True, conexion__requiere_autorizacion=False, proximo_intento__lte=ahora, intentos__lt=5).exclude(conexion__calendario_id="").order_by("proximo_intento").values_list("pk", flat=True)[:limite]
