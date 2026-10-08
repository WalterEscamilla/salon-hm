from django.core.exceptions import ValidationError
from apps.atenciones.forms import AtencionPropuestaForm
from apps.atenciones.services import ClientaAmbigua, resolver_cliente


def avisos_atencion(datos, avisos=()):
    avisos, coincidencias = list(avisos), []
    for campo, aviso in (("nombre_cliente", "Falta el nombre de la clienta."), ("servicio", "Falta precisar el servicio realizado."), ("fecha", "Falta la fecha del servicio; elige el día correcto.")):
        if not datos.get(campo):
            avisos.append(aviso)
    seleccion = datos.get("cliente_id")
    if datos.get("gastos_pagados_en_visita") and (datos.get("costo_materiales") is None or datos.get("otros_gastos") is None):
        avisos.append("Marcaste gastos pagados en esta visita. Completa materiales y otros gastos antes de guardar; usa 0 si no hubo gasto.")
    consulta = AtencionPropuestaForm({**datos, "cliente_id": getattr(seleccion, "pk", seleccion)})
    consulta.is_valid()
    if consulta.cleaned_data.get("nombre_cliente"):
        try:
            resolver_cliente(consulta.cleaned_data)
        except ClientaAmbigua as error:
            coincidencias = error.candidatas
        except ValidationError:
            pass
    if coincidencias:
        avisos.append("Hay posibles coincidencias de clientas. Elige la persona correcta o indica que es otra persona.")
    return list(dict.fromkeys(avisos)), coincidencias
