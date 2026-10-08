from apps.integraciones.crypto import ErrorGoogle
from apps.integraciones.google import GoogleCalendar
from apps.integraciones.models import ConexionGoogle, VinculoEventoGoogle
from apps.integraciones.services import aplicar_eliminacion_google, obtener_conexion
from .models import Cita, RegistroServicioAgenda
from .registro import url_registro_google


def consultar_eventos(actor, inicio, fin, *, zona, citas):
    if not actor.has_perm("integraciones.gestionar_google"):
        return [], ""
    conexion = obtener_conexion(actor)
    if not conexion:
        pendiente = ConexionGoogle.objects.filter(usuario=actor, activa=True).first()
        if pendiente:
            return [], "Reconecta tu cuenta de Google." if pendiente.requiere_autorizacion else "Elige el calendario para las citas en Configurar calendario."
        return [], ""
    adapter = None
    visibles = {cita.pk: cita for cita in citas}
    vinculos_visibles = list(VinculoEventoGoogle.objects.filter(
        conexion=conexion, calendario_id=conexion.calendario_id, cita_id__in=visibles,
    ).select_related("cita"))
    for vinculo in vinculos_visibles:
        visibles[vinculo.cita_id].evento_google = vinculo
    try:
        adapter = GoogleCalendar(conexion)
        eventos = adapter.eventos(inicio, fin, zona=zona)
        presentes = {evento["id"] for evento in eventos}
        eliminados = []
        if actor.has_perm("agenda.change_cita"):
            for vinculo in vinculos_visibles:
                if vinculo.evento_id in presentes or vinculo.cancelado or not vinculo.version_sincronizada:
                    continue
                # Ausente en este intervalo puede significar que se movió.
                # Confirmar por ID antes de cambiar el estado local.
                actual = adapter.obtener_evento(vinculo.calendario_id, vinculo.evento_id)
                if actual is None or actual.get("status") == "cancelled":
                    eliminados.append((vinculo, actual))
        # Un error de consulta impide aplicar cancelaciones parciales.
        for vinculo, actual in eliminados:
            visible = visibles[vinculo.cita_id]
            retirada = aplicar_eliminacion_google(vinculo, cita_version=visible.version, actor=actor, evento=actual)
            if retirada:
                for campo in ("estado", "version", "sincronizacion", "error_sincronizacion"):
                    setattr(visible, campo, getattr(retirada, campo))
                visible.evento_google = retirada.evento_google
    except ErrorGoogle as exc:
        return [], str(exc)
    finally:
        if adapter:
            adapter.close()
    # Solo se oculta la copia de Google si la cita visible tiene el mismo horario.
    # Un evento movido en Google permanece visible hasta revisar el cambio.
    ids = [evento["id"] for evento in eventos]
    vinculos = list(VinculoEventoGoogle.objects.filter(conexion=conexion, calendario_id=conexion.calendario_id, evento_id__in=ids).select_related("cita__registro_servicio"))
    duplicados = {
        v.evento_id: visibles[v.cita_id] for v in vinculos
        if v.cita_id in visibles and not v.cancelado and visibles[v.cita_id].estado != Cita.Estado.CANCELADA
    }
    citas_google = {v.evento_id: v.cita for v in vinculos}
    hechos = dict(RegistroServicioAgenda.objects.filter(usuario=actor, calendario_id=conexion.calendario_id, evento_id__in=ids).values_list("evento_id", "atencion_id"))
    for evento in eventos:
        vinculada = citas_google.get(evento["id"])
        registro = getattr(vinculada, "registro_servicio", None) if vinculada else None
        evento["atencion_id"] = hechos.get(evento["id"]) or (registro.atencion_id if registro else None)
        evento["hecho"] = bool(evento["atencion_id"] or (vinculada and vinculada.estado == Cita.Estado.COMPLETADA))
        evento["puede_registrar"] = not vinculada or (actor.has_perm("agenda.change_cita") and vinculada.estado not in (Cita.Estado.CANCELADA, Cita.Estado.NO_ASISTIO))
        evento["registro_url"] = url_registro_google(conexion.calendario_id, evento["id"])
    return [evento for evento in eventos if not (
        evento["id"] in duplicados
        and not evento["todo_el_dia"]
        and evento["inicio"] == duplicados[evento["id"]].inicio
        and evento["fin"] == duplicados[evento["id"]].fin
    )], ""


def combinar(citas, eventos):
    entradas = []
    for cita in citas:
        if cita.estado == Cita.Estado.CANCELADA:
            continue
        vinculo = getattr(cita, "evento_google", None)
        if vinculo and vinculo.cancelado:
            continue
        registro = getattr(cita, "registro_servicio", None)
        entradas.append({"inicio": cita.inicio, "cita": cita, "atencion_id": registro.atencion_id if registro else None, "hecho": bool(registro or cita.estado == Cita.Estado.COMPLETADA), "puede_registrar": cita.estado not in (Cita.Estado.CANCELADA, Cita.Estado.NO_ASISTIO)})
    entradas.extend({"inicio": evento["inicio"], "evento_google": evento} for evento in eventos)
    return sorted(entradas, key=lambda entrada: entrada["inicio"])
