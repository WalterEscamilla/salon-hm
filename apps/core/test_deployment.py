"""Comprueba HTTPS detrás del proxy sin usar cuentas ni claves reales."""

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse


class RailwaySettingsTests(SimpleTestCase):
    def test_production_settings_accept_railway_domain_and_proxy(self):
        environment = os.environ.copy()
        environment.update({
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "DJANGO_SECRET_KEY": "test-only-" * 8,
            "DJANGO_DEBUG": "False",
            "DJANGO_TRUST_PROXY": "True",
            "DJANGO_SECURE_SSL_REDIRECT": "True",
            "DJANGO_ALLOWED_HOSTS": "localhost",
            "DJANGO_CSRF_TRUSTED_ORIGINS": "",
            "RAILWAY_PUBLIC_DOMAIN": "salon-test.up.railway.app",
            "DATABASE_URL": "postgresql://test:test@127.0.0.1/test_only",
        })
        code = (
            "import json; from django.conf import settings as s; "
            "print(json.dumps({'debug':s.DEBUG,'hosts':s.ALLOWED_HOSTS,"
            "'origins':s.CSRF_TRUSTED_ORIGINS,'proxy':s.SECURE_PROXY_SSL_HEADER,"
            "'secure':s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE,"
            "'middleware':s.MIDDLEWARE,'storage':s.STORAGES['staticfiles']['BACKEND']}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], env=environment, capture_output=True,
            text=True, check=True, cwd=Path(__file__).resolve().parents[2], timeout=15,
        )
        configuration = json.loads(result.stdout)
        self.assertFalse(configuration["debug"])
        self.assertTrue(configuration["secure"])
        self.assertIn("salon-test.up.railway.app", configuration["hosts"])
        self.assertIn("healthcheck.railway.app", configuration["hosts"])
        self.assertIn("https://salon-test.up.railway.app", configuration["origins"])
        self.assertEqual(configuration["proxy"], ["HTTP_X_FORWARDED_PROTO", "https"])
        self.assertEqual(configuration["middleware"][1], "whitenoise.middleware.WhiteNoiseMiddleware")
        self.assertEqual(configuration["storage"], "whitenoise.storage.CompressedManifestStaticFilesStorage")

    @override_settings(
        ALLOWED_HOSTS=["salon-test.up.railway.app", "healthcheck.railway.app"],
        SECURE_SSL_REDIRECT=True,
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        SECURE_REDIRECT_EXEMPT=[r"^health/$"],
    )
    def test_https_proxy_avoids_redirect_loop_and_health_is_public(self):
        login_url = reverse("cuentas:login")
        response = self.client.get(login_url, HTTP_HOST="salon-test.up.railway.app")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.url, f"https://salon-test.up.railway.app{login_url}")
        response = self.client.get(
            login_url, HTTP_HOST="salon-test.up.railway.app", HTTP_X_FORWARDED_PROTO="https",
        )
        self.assertEqual(response.status_code, 200)
        with patch("apps.core.views.connection") as connection:
            connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
            response = self.client.get("/health/", HTTP_HOST="healthcheck.railway.app")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
