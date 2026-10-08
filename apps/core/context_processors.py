from django.conf import settings


def salon_context(request):
    salon = getattr(request, "salon", None)
    return {
        "salon_nombre": salon.nombre if salon else "Salón HM",
        "salon_zona": salon.zona_horaria if salon else settings.TIME_ZONE,
        "salon_moneda": salon.moneda if salon else "MXN",
    }

