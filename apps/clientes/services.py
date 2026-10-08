from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.auditoria.models import EventoAuditoria

from .models import Cliente


@transaction.atomic
def guardar_cliente(*, actor, datos, cliente_id=None, origen="formulario"):
    permiso = "clientes.change_cliente" if cliente_id else "clientes.add_cliente"
    if not actor.has_perm(permiso):
        raise PermissionDenied
    cliente = Cliente.objects.select_for_update().get(pk=cliente_id) if cliente_id else Cliente()
    for campo in ("nombre", "telefono", "notas"):
        setattr(cliente, campo, datos[campo])
    cliente.full_clean()
    cliente.save()
    EventoAuditoria.objects.create(actor=actor, origen=origen, operacion="cliente.editado" if cliente_id else "cliente.creado", entidad="clientes.Cliente", entidad_id=str(cliente.pk))
    return cliente
