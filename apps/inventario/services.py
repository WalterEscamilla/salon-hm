import hashlib
import json
import uuid
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.auditoria.models import EventoAuditoria
from .constants import PRODUCT_CREATED_WITH_STOCK, PRODUCT_ENTITY, PRODUCT_SAVED
from .forms import MovimientoForm, ProductoForm
from .messages import Error, Label
from .models import MovimientoStock, Producto


def serializar(datos):
    return {k: str(v) if isinstance(v, Decimal) else v for k, v in datos.items()}


def huella(datos):
    return hashlib.sha256(json.dumps(datos, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def saldo_resultante(producto, datos):
    if datos["unidad"] != producto.unidad:
        raise ValidationError("La unidad debe coincidir con la del producto. No convertimos gramos a mililitros.")
    cantidad = datos["cantidad"]
    nuevo = cantidad if datos["tipo"] == "ajuste" else producto.existencias + (cantidad if datos["tipo"] == "entrada" else -cantidad)
    if nuevo < 0:
        raise ValidationError("No hay stock suficiente. Revisa la cantidad o registra primero una entrada.")
    if producto.unidad == "unidad" and cantidad != cantidad.to_integral_value():
        raise ValidationError("Los productos contados por unidades necesitan cantidades enteras.")
    if not producto.activo:
        raise ValidationError("Activa el producto antes de registrar movimientos.")
    return nuevo


@transaction.atomic
def guardar_producto(*, actor, datos, producto_id=None, origen="formulario"):
    if not actor.has_perm("inventario.change_producto" if producto_id else "inventario.add_producto"):
        raise PermissionDenied
    if producto_id and datos.get("cantidad_inicial") not in (None, ""):
        raise ValidationError(Error.InitialStockOnEdit)
    producto = Producto.objects.select_for_update().get(pk=producto_id) if producto_id else Producto()
    form = ProductoForm(datos, instance=producto)
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    cantidad = form.cleaned_data.get("stock_inicial_calculado")
    if cantidad is not None and not actor.has_perm("inventario.add_movimientostock"):
        raise PermissionDenied
    clave = form.cleaned_data.get("clave_alta") if not producto_id else None
    fingerprint = huella({"datos": {campo: valor for campo, valor in form.cleaned_data.items() if campo != "clave_alta"}, "actor": actor.pk, "origen": origen}) if clave else ""
    # ModelForm muta su instancia durante la validación: consultar la unidad almacenada.
    if producto_id and Producto.objects.get(pk=producto_id).unidad != form.cleaned_data["unidad"] and producto.movimientos.exists():
        raise ValidationError("Un producto con movimientos conserva su unidad. Crea otro producto para otra presentación.")
    producto = form.save(commit=False)
    if clave:
        producto.clave_alta, producto.huella_alta = clave, fingerprint
    if producto_id:
        producto.version += 1
    producto.full_clean(validate_unique=not bool(clave))
    if clave:
        # La restricción única y get_or_create resuelven también envíos concurrentes.
        defaults = {campo: getattr(producto, campo) for campo in ProductoForm._meta.fields}
        producto, creado = Producto.objects.get_or_create(clave_alta=clave, defaults={**defaults, "huella_alta": fingerprint})
        if not creado:
            if producto.huella_alta != fingerprint:
                raise ValidationError(Error.OperationConflict)
            return producto
    else:
        producto.save()
    EventoAuditoria.objects.create(actor=actor, origen=origen, operacion=PRODUCT_SAVED, entidad=PRODUCT_ENTITY, entidad_id=str(producto.pk))
    if cantidad is not None:
        registrar_movimiento(actor=actor, producto_id=producto.pk, origen=origen, datos={
            "tipo": MovimientoStock.Tipo.AJUSTE, "cantidad": cantidad, "unidad": producto.unidad,
            "motivo": Label.InitialStockReason, "version": producto.version,
            "clave_operacion": clave or uuid.uuid4(),
        })
        producto.refresh_from_db()
        EventoAuditoria.objects.create(actor=actor, origen=origen, operacion=PRODUCT_CREATED_WITH_STOCK, entidad=PRODUCT_ENTITY, entidad_id=str(producto.pk), cambios={
            "cantidad": str(form.cleaned_data["cantidad_inicial"]), "modo": form.cleaned_data["modo_cantidad"],
            "total": str(cantidad), "unidad": producto.unidad,
        })
    return producto


@transaction.atomic
def registrar_movimiento(*, actor, producto_id, datos, origen="formulario"):
    if not actor.has_perm("inventario.add_movimientostock"):
        raise PermissionDenied
    form = MovimientoForm(datos)
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    datos = form.cleaned_data
    producto = Producto.objects.select_for_update().get(pk=producto_id)
    contenido = {k: v for k, v in datos.items() if k not in ("version", "clave_operacion")}
    fingerprint = huella({**contenido, "producto_id": producto_id, "actor": actor.pk, "origen": origen})
    previo = MovimientoStock.objects.filter(clave_operacion=datos["clave_operacion"]).first()
    if previo:
        if previo.huella != fingerprint:
            raise ValidationError("Esta operación ya se utilizó con otros datos.")
        return previo
    if producto.version != datos["version"]:
        raise ValidationError("El producto o sus existencias cambiaron. Recarga y revisa el nuevo saldo.")
    nuevo = saldo_resultante(producto, datos)
    movimiento = MovimientoStock(producto=producto, actor=actor, tipo=datos["tipo"], cantidad=datos["cantidad"], unidad=producto.unidad, saldo_anterior=producto.existencias, saldo_nuevo=nuevo, costo_por_unidad=producto.costo_por_unidad, motivo=datos["motivo"], origen=origen, clave_operacion=datos["clave_operacion"], huella=fingerprint)
    # Redondear únicamente el snapshot del costo, nunca la cantidad del movimiento.
    if movimiento.costo_por_unidad is not None:
        movimiento.costo_por_unidad = movimiento.costo_por_unidad.quantize(Decimal("0.000001"))
    movimiento.full_clean()
    movimiento.save()
    producto.existencias = nuevo
    producto.version += 1
    producto.full_clean()
    producto.save(update_fields=["existencias", "version"])
    EventoAuditoria.objects.create(actor=actor, origen=origen, operacion="stock.movimiento", entidad="inventario.MovimientoStock", entidad_id=str(movimiento.pk), cambios={"producto_id": producto.pk, "antes": str(movimiento.saldo_anterior), "despues": str(nuevo), "unidad": producto.unidad})
    return movimiento
