from django.db import migrations


def crear_configuracion(apps, schema_editor):
    ConfiguracionSalon = apps.get_model("configuracion", "ConfiguracionSalon")
    ConfiguracionSalon.objects.using(schema_editor.connection.alias).get_or_create(
        pk=1, defaults={"nombre": "Salón HM", "moneda": "MXN", "zona_horaria": "America/Merida"},
    )


class Migration(migrations.Migration):
    dependencies = [("configuracion", "0001_initial")]
    operations = [migrations.RunPython(crear_configuracion, migrations.RunPython.noop)]

