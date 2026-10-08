"""Servidor Linux de producción. El puerto lo proporciona Railway."""

import os

bind = f"0.0.0.0:{int(os.environ.get('PORT', '8000'))}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
timeout = 120
graceful_timeout = 30
errorlog = "-"
# Las URLs OAuth y los enlaces firmados pueden llevar credenciales en la query.
# %(U)s registra solo la ruta; no registrar %(r)s, %(q)s ni Referer.
accesslog = "-"
access_log_format = '%(h)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s %(L)s'
