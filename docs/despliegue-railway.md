# Desplegar Salón HM en Railway

El repositorio es `WalterEscamilla/salon-hm`. Railway construye el `Dockerfile`
con Python 3.13, prepara los archivos estáticos y ejecuta Gunicorn en el puerto
`PORT`. El build no necesita claves ni conexión a PostgreSQL.

## 1. Crear el proyecto y PostgreSQL

En Railway crea un proyecto y añade una base **PostgreSQL** llamada `Postgres`.
Mantén su volumen persistente. La aplicación y el proceso de Calendar compartirán
esta base mediante la red privada del proyecto.

Si vamos a conservar los datos locales, espera a terminar la importación antes
de aplicar migraciones, crear usuarios o iniciar el proceso de Calendar. Una
base PostgreSQL recién creada está vacía; no incluye automáticamente `salon_hm`.
No borres ni reemplaces la base local.

## 2. Añadir la web desde GitHub

Añade un servicio desde **GitHub Repo**, selecciona
`WalterEscamilla/salon-hm` y la rama `main`. Autoriza a Railway a leer ese
repositorio si lo solicita. Llámalo `web`.

El primer intento puede fallar mientras faltan variables. Configúralas antes
de volver a desplegar. Usa **Variables**, no un archivo `.env` en GitHub:

```dotenv
DJANGO_DEBUG=False
DJANGO_TRUST_PROXY=True
DATABASE_URL=${{Postgres.DATABASE_URL}}
DJANGO_SECRET_KEY=CLAVE_ALEATORIA_DE_PRODUCCION
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
WEB_CONCURRENCY=2
GUNICORN_THREADS=2
GOOGLE_CLIENT_ID=EL_ID_DE_TU_CLIENTE_GOOGLE
GOOGLE_CLIENT_SECRET=EL_SECRETO_DE_TU_CLIENTE_GOOGLE
GOOGLE_LOGIN_EMAIL=EL_CORREO_AUTORIZADO_DE_MARISOL
GOOGLE_LOGIN_USERNAME=Marisol
GOOGLE_TOKEN_ENCRYPTION_KEY=LA_CLAVE_FERNET_ACTUAL
GOOGLE_REDIRECT_URI=https://TU_DOMINIO/calendario/google/retorno/
OPENAI_API_KEY=TU_CLAVE_OPENAI
OPENAI_MODEL=gpt-5.4-mini
OPENAI_DAILY_REQUEST_LIMIT=60
```

Sustituye los ejemplos con tus valores reales desde `.env`. No copies las
variables locales `POSTGRES_HOST`, `POSTGRES_USER` o `POSTGRES_PASSWORD`: la
referencia `DATABASE_URL` utiliza las credenciales del PostgreSQL de Railway.
Si cambias el nombre del servicio `Postgres`, cambia también esa referencia.

Conserva la misma `GOOGLE_TOKEN_ENCRYPTION_KEY` si importamos la base actual:
permite descifrar los tokens de Calendar ya guardados. Esta clave debe
respaldarse por separado de la base. No la regeneres en cada despliegue.

Para generar una nueva clave Django, ejecuta localmente:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(64))"
```

Cópiala directamente a las variables de Railway. Una clave nueva invalidará
las sesiones anteriores y los enlaces firmados; los registros se conservan.

En **Settings → Deploy** establece:

| Opción | Valor |
| --- | --- |
| Pre-deploy command | `python manage.py migrate --noinput` |
| Start command | Dejar vacío: utiliza el `CMD` del Dockerfile |
| Healthcheck path | `/health/` |
| Healthcheck timeout | `300` segundos |
| Restart policy | On failure |
| Replicas | `1` |

No pongas `collectstatic` en el pre-deploy: ya se ejecuta en el Dockerfile y
sus archivos forman parte de la imagen. El pre-deploy se ejecuta en otro
contenedor y sus archivos no pasan a la web.

En **Settings → Networking → Generate Domain** genera la dirección pública.
Django acepta automáticamente `RAILWAY_PUBLIC_DOMAIN` y su origen HTTPS;
también admite `healthcheck.railway.app` para las comprobaciones de Railway.
Para un dominio propio, añádelo a `DJANGO_ALLOWED_HOSTS` y agrega su URL
`https://...` a `DJANGO_CSRF_TRUSTED_ORIGINS`.

## 3. Configurar Google para la dirección pública

Cambia `GOOGLE_REDIRECT_URI` en Railway por la URL exacta:

```text
https://TU_DOMINIO/calendario/google/retorno/
```

En **Google Cloud → Google Auth Platform → Clientes** abre el mismo cliente
OAuth y agrega esta URL en **URI de redirección autorizados**. Puedes mantener
la dirección local para seguir desarrollando. El correo autorizado debe seguir
en los usuarios de prueba mientras el proyecto Google esté en modo Testing.

Despliega con los cambios, abre la dirección HTTPS y entra con Google. Si no
importamos los usuarios, primero debes crear la cuenta local `Marisol`; el
acceso Google vincula esa cuenta existente y no permite registro público.

En **Calendario** comprueba la conexión y el calendario seleccionado. Si los
tokens importados han caducado, vuelve a conectar Google desde la nueva URL.

## 4. Añadir el proceso de sincronización

Añade otro servicio desde el mismo repositorio y rama. Llámalo `calendar-worker`.
Comparte las variables de la web, especialmente `DATABASE_URL`,
`DJANGO_SECRET_KEY`, las credenciales Google y la clave de cifrado. Puedes usar
variables compartidas de Railway. No necesita `OPENAI_API_KEY` ni dominio público.

Configura este servicio:

| Opción | Valor |
| --- | --- |
| Start command | `python manage.py sincronizar_calendario --continuo` |
| Pre-deploy command | Vacío |
| Healthcheck path | Vacío |
| Replicas | `1` |
| Restart policy | On failure |

Actívalo después de que las migraciones de la web hayan terminado. En cambios
futuros de esquema, comprueba primero las migraciones antes de reiniciar este
proceso. PostgreSQL contiene los trabajos pendientes; no se necesita Redis.

El proceso envía a Google las citas guardadas en el salón. Los eventos nuevos
creados en Google se consultan al abrir la agenda y mientras está visible,
aproximadamente cada minuto. Para consultar Google no hace falta crear copias
automáticas de todas sus citas en la base del salón.

## 5. Conservar los datos o iniciar una base nueva

Para conservarlos: respalda `salon_hm` en formato custom de `pg_dump`, importa
en el PostgreSQL vacío de Railway con `pg_restore --no-owner --no-privileges`
y después ejecuta las migraciones. Los usuarios, catálogo, historial y
conexiones cifradas viajan con la base; las claves se copian por separado.
La importación desde tu PC requiere la conexión pública de PostgreSQL con SSL;
la web y el worker usan la conexión privada. No importes sobre una base con
registros nuevos sin revisar primero cómo combinarlos. Los respaldos están
excluidos de Git y de Docker.

Para iniciar de cero, una vez aplicadas las migraciones entra al contenedor
web con la CLI de Railway:

```powershell
railway login
railway link
railway ssh --service web
```

Dentro del contenedor ejecuta:

```bash
python manage.py preparar_acceso
```

Usa el nombre `Marisol`, el correo autorizado y una contraseña propia de al
menos 12 caracteres para el acceso público. Este comando solicita la contraseña
sin mostrarla. No lo ejecutes si ya importamos la administradora existente.
`railway run` ejecuta comandos en tu PC; para usar la conexión privada de
PostgreSQL necesitas `railway ssh` o un comando dentro de Railway.

## 6. Comprobar antes de usarlo

1. Abre `https://TU_DOMINIO/health/`: debe devolver `{"status":"ok"}`.
2. Comprueba el acceso privado, Google y que se cargan estilos y JavaScript.
3. Revisa que aparecen los datos importados y las citas del calendario elegido.
4. En la siguiente cita real, registra el servicio y verifica su historial y la
   marca **Hecho**. La interpretación con IA prepara el formulario; guardar sigue
   requiriendo la confirmación de Marisol.
5. Comprueba que `calendar-worker` permanece activo y que no hay trabajos fallidos.
6. Activa los respaldos de PostgreSQL y conserva las claves fuera del repositorio.

Con GitHub conectado, los siguientes cambios enviados a `main` pueden desplegar
automáticamente los dos servicios. La web aplica migraciones antes de arrancar.
La facturación se gestiona en tu cuenta de Railway; comprueba sus límites y
consumo antes de dejar los tres servicios funcionando permanentemente.

Referencias oficiales: [Django en Railway](https://docs.railway.com/guides/django),
[pre-deploy](https://docs.railway.com/deployments/pre-deploy-command),
[healthchecks](https://docs.railway.com/deployments/healthchecks),
[WhiteNoise](https://whitenoise.readthedocs.io/en/stable/django.html).
