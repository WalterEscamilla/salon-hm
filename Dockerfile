FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt \
    && useradd --create-home salonhm
COPY --chown=salonhm:salonhm . .
RUN python manage.py collectstatic --noinput --settings=config.settings_static
USER salonhm
EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--config", "config/gunicorn.py"]
