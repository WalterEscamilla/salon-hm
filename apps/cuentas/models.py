from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    google_sub = models.CharField(max_length=255, unique=True, null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "usuaria o usuario"
        verbose_name_plural = "usuarios"
