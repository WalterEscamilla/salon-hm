from zoneinfo import ZoneInfo

from django.db import migrations
from django.utils import timezone


def crear_base(apps, schema_editor):
    salon = apps.get_model("configuracion", "ConfiguracionSalon").objects.using(schema_editor.connection.alias).get(pk=1)
    fecha = timezone.localdate(timezone.now(), timezone=ZoneInfo(salon.zona_horaria))
    apps.get_model("finanzas", "BaseFinanciera").objects.using(schema_editor.connection.alias).get_or_create(pk=1, defaults={"saldo_inicial": "10000.00", "fecha_inicio": fecha})


class Migration(migrations.Migration):
    dependencies = [("finanzas", "0001_initial"), ("configuracion", "0002_configuracion_inicial")]
    operations = [migrations.RunPython(crear_base, migrations.RunPython.noop)]
