from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.auditoria.models import EventoAuditoria
from apps.configuracion.models import ConfiguracionSalon
from apps.inventario.services import huella
from .forms import AnularGastoForm, BaseFinancieraForm, GastoForm
from .models import BaseFinanciera, Gasto


def validar(form):
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    return form.cleaned_data


def datos_gasto(gasto):
    return {campo: str(getattr(gasto, campo)) for campo in ("fecha", "concepto", "categoria", "importe", "notas", "anulado_en", "motivo_anulacion")}


def auditar(actor, objeto, operacion, antes, despues):
    EventoAuditoria.objects.create(actor=actor, origen="formulario", operacion=operacion, entidad=objeto._meta.label, entidad_id=str(objeto.pk), cambios={"antes": antes, "despues": despues})


@transaction.atomic
def guardar_gasto(*, actor, datos, gasto_id=None):
    if not actor.has_perm("finanzas.change_gasto" if gasto_id else "finanzas.add_gasto"):
        raise PermissionDenied
    datos = validar(GastoForm(datos))
    ConfiguracionSalon.objects.select_for_update().get(pk=1)
    fingerprint = huella({k: v for k, v in datos.items() if k != "version"} | {"actor": actor.pk})
    if not gasto_id:
        previo = Gasto.objects.filter(clave_operacion=datos["clave_operacion"]).first()
        if previo:
            if previo.huella_operacion != fingerprint:
                raise ValidationError("Esta operación ya se guardó con otros datos.")
            return previo
    gasto = Gasto.objects.select_for_update().get(pk=gasto_id) if gasto_id else Gasto(actor=actor, clave_operacion=datos["clave_operacion"], huella_operacion=fingerprint)
    if gasto_id and (gasto.anulado_en or gasto.version != datos["version"]):
        raise ValidationError("El gasto cambió o fue anulado. Recarga antes de corregirlo.")
    antes = datos_gasto(gasto) if gasto_id else {}
    for campo in ("fecha", "concepto", "categoria", "importe", "notas"):
        setattr(gasto, campo, datos[campo])
    if gasto_id:
        gasto.version += 1
    gasto.full_clean()
    gasto.save()
    auditar(actor, gasto, "gasto.editado" if gasto_id else "gasto.creado", antes, datos_gasto(gasto))
    return gasto


@transaction.atomic
def anular_gasto(*, actor, gasto_id, datos):
    if not actor.has_perm("finanzas.change_gasto"):
        raise PermissionDenied
    datos = validar(AnularGastoForm(datos))
    ConfiguracionSalon.objects.select_for_update().get(pk=1)
    gasto = Gasto.objects.select_for_update().get(pk=gasto_id)
    if gasto.anulado_en:
        return gasto
    if gasto.version != datos["version"]:
        raise ValidationError("El gasto cambió. Recarga antes de anularlo.")
    antes = datos_gasto(gasto)
    gasto.anulado_en = timezone.now()
    gasto.motivo_anulacion = datos["motivo"]
    gasto.version += 1
    gasto.full_clean()
    gasto.save()
    auditar(actor, gasto, "gasto.anulado", antes, datos_gasto(gasto))
    return gasto


@transaction.atomic
def guardar_base(*, actor, datos):
    if not actor.has_perm("finanzas.change_basefinanciera"):
        raise PermissionDenied
    datos = validar(BaseFinancieraForm(datos))
    ConfiguracionSalon.objects.select_for_update().get(pk=1)
    base = BaseFinanciera.objects.select_for_update().get(pk=1)
    if base.version != datos["version"]:
        raise ValidationError("La base cambió en otra ventana. Recarga antes de editarla.")
    antes = {"saldo_inicial": str(base.saldo_inicial), "fecha_inicio": base.fecha_inicio.isoformat()}
    base.saldo_inicial, base.fecha_inicio = datos["saldo_inicial"], datos["fecha_inicio"]
    base.version += 1
    base.full_clean()
    base.save()
    auditar(actor, base, "finanzas.base_editada", antes, {"saldo_inicial": str(base.saldo_inicial), "fecha_inicio": base.fecha_inicio.isoformat()})
    return base
