# Salón HM

Aplicación privada para administrar el salón desde el celular. Entrega actual:
acceso privado, clientas con historial de servicios realizados, finanzas, productos, stock manual, asistente OpenAI y conexión Google Calendar preparada.
[Diseño y alcance](docs/diseno-inicial.md), [guía de Google Calendar](docs/google-calendar.md),
[asistente e inventario](docs/asistente-e-inventario.md).
La [guía de registro diario](docs/registro-diario.md) describe el flujo simplificado para Marisol.
La [guía de Finanzas](docs/finanzas.md) explica el saldo inicial de $10,000, los gastos y los costos por visita.
Para publicarlo, sigue la [guía de despliegue en Railway](docs/despliegue-railway.md).

## Qué funciona

- Usuario propio de Django, sin registro público ni contraseña predeterminada.
- Inicio de sesión y salida por POST con CSRF; rutas privadas por defecto.
- Inicio responsive en español con citas reales del día.
- Clientas con búsqueda por nombre/teléfono y selección por identificador, incluso con nombres iguales.
- Catálogo de servicios: solo el nombre es obligatorio; precio y duración de referencia son opcionales.
- Registro de servicios realizados con resolución de clientas, precios por visita, materiales libres y consulta de la última atención.
- Finanzas con saldo inicial configurable, gastos corregibles o anulables, costos de materiales y otros gastos por visita, margen y distinción entre consumo y dinero pagado para evitar descontar dos veces una compra.
- [Acceso con Google](docs/acceso-google.md) para la cuenta autorizada, vinculado a la usuaria existente.
- Productos, existencias por unidad, costos opcionales, avisos de stock bajo y movimientos auditados.
- Asistente OpenAI con consultas y borradores editables, confirmación humana e idempotencia.
- Agenda de día, semana y próximas citas; alta, edición, estados y traslapes aceptados explícitamente.
- Citas sin duplicados por doble clic y sin cobros o atenciones automáticos.
- Conexión Google mediante OAuth, calendario elegido, tokens cifrados, cola persistente y conflictos externos.
- Nombre y zona horaria configurables por la administradora; moneda MXN.
- Fechas conscientes de zona, almacenadas en UTC y presentadas en hora del salón.
- Cambios de configuración auditados dentro de la misma transacción.
- Migraciones de usuarios, configuración inicial y auditoría.
- Health check público en `/health/`: comprueba PostgreSQL sin exponer datos internos.
- Bootstrap y HTMX locales. Los formularios no dependen de JavaScript.

Todavía faltan archivo de clientas, fórmulas estructuradas y consumos de inventario vinculados a atenciones,
pagos y anticipos. La configuración de producción está preparada para Railway; el historial se
importará después de conocer su formato. La conexión Google requiere crear las
credenciales OAuth y una validación real con tu cuenta; las pruebas externas usan dobles.

## Agregar una cita

Entra con tu cuenta. En Inicio o Agenda pulsa **Nueva cita**. Selecciona la clienta;
si no existe, pulsa **Crear una clienta**, guarda su nombre y vuelve al formulario.
Escribe el servicio previsto o selecciona servicios del catálogo; indica inicio y fin
y pulsa **Guardar cita**. Si hay traslapes, cambia el horario o acepta la advertencia
para el caso especial. Para cancelar o cambiar el estado, abre la cita y pulsa **Editar cita**.
El catálogo de servicios se abre desde Inicio. No se han sembrado precios ni clientas ficticias en la base real.

Para conectar Google entra a **Calendario** y sigue la [guía paso a paso](docs/google-calendar.md).

## Inicio en la PC actual (Windows)

Se prepararon Python 3.13 en `.tools` y un entorno `.venv`. La aplicación usa tu
base existente **salon_hm**, indicada en `.env`. Completa sus credenciales reales:

```dotenv
POSTGRES_DB=salon_hm
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=TU_USUARIO_POSTGRESQL
POSTGRES_PASSWORD="TU_CONTRASEÑA_POSTGRESQL"
DATABASE_URL=
```

Son las credenciales de PostgreSQL, independientes de la cuenta administradora del
salón. Las comillas de la contraseña se eliminan al leer `.env`; los símbolos se
conservan sin codificar una URL. Ajusta host y puerto si tu servidor usa otros valores.
Una `DATABASE_URL` no vacía tiene prioridad sobre estos campos; déjala vacía aquí.
El servicio PostgreSQL debe estar iniciado. `.env` está excluido de Git y no se comparte.

Desde PowerShell en esta carpeta:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\iniciar-local.ps1
```

El script usa el PostgreSQL configurado, aplica migraciones y solicita crear la administradora
si aún no existe. Usa una contraseña propia de al menos 12 caracteres. Luego abre
**http://127.0.0.1:8010**. Mantén la terminal abierta; Ctrl+C detiene Django.
El `ExecutionPolicy Bypass` aplica solo a este proceso; no cambia la configuración del sistema.
La primera vez, el correo puede dejarse vacío. No se envían correos.

El script no crea una base nueva ni inicia o detiene el servicio PostgreSQL existente.
Las migraciones crean las tablas de la aplicación dentro de `salon_hm`.

Para cambiar la contraseña de la cuenta creada:

```powershell
.\.venv\Scripts\python.exe manage.py changepassword TU_USUARIO
```

La instancia aislada de la primera entrega sigue separada en `.tools/pg-data`; ya
no se usa al iniciar. Su configuración anterior quedó respaldada dentro de `.tools`.
Esta ruta de inicio aprovecha el entorno preparado aquí; las carpetas `.tools` y
`.venv` no se incluyen en Git ni en Docker y no se copian a otra PC.

## Instalación reproducible con Docker

Requisitos: Docker con Compose. En Windows puede usarse Docker Desktop con WSL2.
Docker no estaba instalado en la PC durante esta entrega; el build y Compose aún
requieren validación real en un equipo con Docker. Esta alternativa usa una base
separada dentro de Docker: para usar tu `salon_hm` existente, usa el inicio local anterior.

1. Copia `.env.example` a `.env` si no tienes ya un entorno local. No sobrescribas tus claves.
2. Configura `POSTGRES_USER` para el contenedor, `DJANGO_SECRET_KEY` con una clave aleatoria y `POSTGRES_PASSWORD` con
   una contraseña aleatoria de letras y números, sin espacios. No uses las mismas claves
   en producción. Puedes generar cada valor con este comando y copiarlo solo a tu `.env`:

```powershell
docker run --rm python:3.13-slim python -c "import secrets; print(secrets.token_hex(32))"
```

3. Construye, migra y crea tu cuenta:

```powershell
docker compose build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py preparar_acceso
docker compose up -d
```

Abre **http://127.0.0.1:8010**. Compose configura la conexión interna al host `db`,
puerto 5432, con los campos `POSTGRES_*`. PostgreSQL no se
publica en un puerto del host. La web se publica solo en 127.0.0.1.
No ejecutes simultáneamente el servidor local y Compose en el mismo puerto 8010.

```powershell
docker compose logs -f web
docker compose down
```

`down` conserva el volumen de datos. Cambiar `POSTGRES_PASSWORD` en `.env` después
de inicializar un volumen no modifica automáticamente la contraseña dentro de PostgreSQL.
El Dockerfile usa Gunicorn y sirve los archivos estáticos con WhiteNoise. Compose
mantiene el servidor de desarrollo para el entorno local.

## Otra instalación con Python y PostgreSQL

Requisitos: Python 3.13 y PostgreSQL 16 o 17. El entorno Docker usa PostgreSQL 17.
Usa la base `salon_hm` y un usuario con acceso a ella. Configura los campos
`POSTGRES_*`, `DJANGO_SECRET_KEY` y `DJANGO_DEBUG=True` en `.env`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py preparar_acceso
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8010
```

En Linux/macOS usa `.venv/bin/python` en lugar de `.venv\Scripts\python.exe`.

## Validación

Con PostgreSQL local iniciado:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test
```

En Docker:

```powershell
docker compose run --rm web python manage.py check
docker compose run --rm web python manage.py makemigrations --check --dry-run
docker compose run --rm web python manage.py test
```

Las pruebas usan una base PostgreSQL temporal distinta: el usuario de pruebas necesita
permiso CREATEDB. No apuntes las pruebas al usuario o servidor de producción.
Se comprueban login, rutas privadas, credenciales inválidas, usuario inactivo, CSRF,
redirecciones seguras, permisos, zona horaria, configuración única y rollback de auditoría.

Prueba manual: entrar, cambiar el nombre/zona en Configuración, regresar a Inicio y
cerrar sesión. Probar a 390 px de ancho o con las herramientas de dispositivo del navegador.
Para ver auditoría como administradora, abre `/admin/`.

## Organización y siguientes etapas

`config/`: ajustes y rutas del proyecto. `apps/`: módulos. `templates/`: interfaz.
`static/`: CSS, Bootstrap, HTMX y recursos locales. `docs/`: diseño y entregas.
`requirements.in` declara dependencias; `requirements.txt` fija versiones y hashes
para Windows/Linux. Actualízalo con `uv pip compile requirements.in --generate-hashes
--universal --python-version 3.13 --output-file requirements.txt` y repite los controles.

1. Base local (esta entrega).
2. Clientes, servicios y productos con datos ficticios.
3. Atenciones, fórmulas, costos y pagos.
4. Agenda y anticipos: traslapes aceptados explícitamente y aplicación sin duplicar ingresos.
5. Google Calendar con OAuth, reintentos y conflictos externos.
6. Asistente con Responses API y confirmación humana de cada escritura.
7. Railway, migraciones, estáticos, respaldos y restauración.

## Seguridad y operación

Mantén `.env` fuera de Git. Puedes completar `OPENAI_API_KEY` en ese archivo para la
integración del asistente; se llama a OpenAI al enviar mensajes. Google solo se conecta después de configurar OAuth.
El nombre de esta variable corresponde a la [documentación oficial de OpenAI](https://developers.openai.com/api/docs/quickstart).
Las cuentas se crean localmente por consola; no se publican credenciales demo.
Con `DJANGO_DEBUG=False` se activan cookies seguras y redirección HTTPS; antes de
producción habrá que configurar servidor, dominio, proxy HTTPS, estáticos y backups.
No publiques el servidor `runserver` en internet.
El endpoint health hace únicamente una consulta constante; las operaciones de negocio
usan el ORM. La configuración del salón se guarda mediante su servicio de negocio,
que vuelve a validar los datos y permisos aunque se llame sin un formulario.

Documentación consultada para esta etapa:

- [Autenticación de Django](https://docs.djangoproject.com/en/5.2/topics/auth/default/).
- [Usuario personalizado](https://docs.djangoproject.com/en/5.2/topics/auth/customizing/).
- [Lista de despliegue seguro](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
- [Bootstrap](https://getbootstrap.com/docs/5.3/getting-started/download/).
- [HTMX](https://htmx.org/docs/).
