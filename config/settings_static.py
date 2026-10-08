"""Ajustes exclusivos de collectstatic: el build no necesita claves ni PostgreSQL."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "collectstatic-only-never-use-for-the-application"
DEBUG = False
INSTALLED_APPS = ["django.contrib.staticfiles"]
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
