from .models import ConfiguracionSalon


def obtener_configuracion():
    return ConfiguracionSalon.objects.get(pk=1)

