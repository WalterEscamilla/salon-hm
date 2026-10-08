import time

from django.core.management.base import BaseCommand

from apps.integraciones.services import procesar_trabajo, trabajos_pendientes


class Command(BaseCommand):
    help = "Procesa trabajos persistidos de Google Calendar, sin una cola externa."

    def add_arguments(self, parser):
        parser.add_argument("--continuo", action="store_true")

    def handle(self, *args, **options):
        try:
            while True:
                for pk in list(trabajos_pendientes()):
                    procesar_trabajo(pk)
                if not options["continuo"]:
                    self.stdout.write("Procesamiento terminado. Revisa los estados en la agenda.")
                    return
                time.sleep(5)
        except KeyboardInterrupt:
            self.stdout.write("Procesador detenido.")

