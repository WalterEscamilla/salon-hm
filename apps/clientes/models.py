import re

from django.core.exceptions import ValidationError
from django.db import models
from .identidad import normalizar_nombre


class Cliente(models.Model):
    nombre = models.CharField("Nombre completo", max_length=160)
    nombre_normalizado = models.CharField(max_length=160, blank=True, db_index=True, editable=False)
    telefono = models.CharField("Teléfono", max_length=30, blank=True)
    telefono_normalizado = models.CharField(max_length=30, blank=True, db_index=True)
    notas = models.TextField(blank=True, max_length=3000)
    archivado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nombre", "pk"]

    def clean(self):
        super().clean()
        self.nombre = self.nombre.strip()
        if not self.nombre:
            raise ValidationError({"nombre": "Escribe el nombre de la clienta."})
        self.telefono_normalizado = re.sub(r"\D", "", self.telefono)
        self.nombre_normalizado = normalizar_nombre(self.nombre)

    def __str__(self):
        identificacion = self.telefono or "Sin teléfono"
        return f"{self.nombre} · {identificacion} · ID {self.pk}"
