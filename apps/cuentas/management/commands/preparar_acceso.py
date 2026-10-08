from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Solicita crear la administradora únicamente si aún no existe una."

    def handle(self, *args, **options):
        if get_user_model().objects.filter(is_superuser=True).exists():
            self.stdout.write("La cuenta administradora ya está creada.")
            return
        self.stdout.write("Crea la cuenta administradora. La contraseña no se mostrará ni quedará en archivos.")
        call_command("createsuperuser", interactive=True)

