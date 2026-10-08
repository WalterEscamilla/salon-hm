from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.auditoria.models import EventoAuditoria

from .models import ConfiguracionSalon


@transaction.atomic
def actualizar_configuracion(*, actor, nombre, zona_horaria):
    if not actor.is_authenticated or not actor.has_perm("configuracion.change_configuracionsalon"):
        raise PermissionDenied
    salon = ConfiguracionSalon.objects.select_for_update().get(pk=1)
    antes = {"nombre": salon.nombre, "zona_horaria": salon.zona_horaria}
    salon.nombre = nombre
    salon.zona_horaria = zona_horaria
    salon.full_clean()
    despues = {"nombre": salon.nombre, "zona_horaria": salon.zona_horaria}
    if antes != despues:
        salon.save(update_fields=["nombre", "zona_horaria", "actualizado_en"])
        EventoAuditoria.objects.create(
            actor=actor, origen="formulario", operacion="configuracion.actualizada",
            entidad="configuracion.ConfiguracionSalon", entidad_id="1",
            cambios={"antes": antes, "despues": despues},
        )
    return salon

