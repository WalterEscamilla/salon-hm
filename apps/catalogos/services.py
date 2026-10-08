from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.auditoria.models import EventoAuditoria

from .models import Servicio


@transaction.atomic
def guardar_servicio(*, actor, datos, servicio_id=None, origen="formulario"):
    permiso = "catalogos.change_servicio" if servicio_id else "catalogos.add_servicio"
    if not actor.has_perm(permiso):
        raise PermissionDenied
    servicio = Servicio.objects.select_for_update().get(pk=servicio_id) if servicio_id else Servicio()
    for campo in ("nombre", "descripcion", "duracion_minutos", "precio_base", "activo"):
        if campo in datos:
            setattr(servicio, campo, datos[campo])
        elif not servicio_id:
            setattr(servicio, campo, {"descripcion": "", "activo": True}.get(campo))
    servicio.full_clean()
    servicio.save()
    EventoAuditoria.objects.create(actor=actor, origen=origen, operacion="servicio.guardado", entidad="catalogos.Servicio", entidad_id=str(servicio.pk))
    return servicio
