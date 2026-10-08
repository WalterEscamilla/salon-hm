from .models import Cita


def citas_en_intervalo(inicio, fin):
    return Cita.objects.filter(inicio__lt=fin, fin__gt=inicio).select_related("cliente", "responsable", "registro_servicio").prefetch_related("servicios_previstos")


def buscar_traslapes(inicio, fin, excluir=None):
    citas = citas_en_intervalo(inicio, fin).filter(estado__in=[Cita.Estado.PENDIENTE, Cita.Estado.CONFIRMADA])
    if excluir:
        citas = citas.exclude(pk=excluir)
    return list(citas)
