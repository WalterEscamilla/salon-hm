# Conectar Google Calendar con Salón HM

La agenda local ya funciona sin Google. La conexión requiere configurar un proyecto
OAuth y autorizar tu cuenta; no se usa la contraseña de Gmail ni la clave de OpenAI.

Para entrar al salón con el Gmail de Marisol consulta [Acceso con Google](acceso-google.md).
El inicio de sesión comparte la URI de retorno y tiene permisos de identidad separados.

## Configuración de Google

1. Abre [Google Cloud Console](https://console.cloud.google.com/) y crea o elige un
   proyecto, por ejemplo `Salon HM`.
2. En **APIs y servicios → Biblioteca**, habilita **Google Calendar API**.
3. En **Google Auth Platform**, configura la marca y audiencia de la aplicación.
   Para una cuenta Gmail personal, elige audiencia externa. Mientras esté en pruebas,
   agrega el Gmail de Marisol a la lista de usuarios de prueba.
4. En **Clientes**, crea un cliente de tipo **Aplicación web**. En las URI de
   redirección autorizadas agrega exactamente:

```text
http://127.0.0.1:8010/calendario/google/retorno/
```

5. Copia el ID y el secreto a `.env`, sin compartirlos en el chat ni en Git:

```dotenv
GOOGLE_CLIENT_ID=TU_ID.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=TU_SECRETO
GOOGLE_REDIRECT_URI=http://127.0.0.1:8010/calendario/google/retorno/
```

`GOOGLE_TOKEN_ENCRYPTION_KEY` ya se generó en el entorno local. No la cambies al
reiniciar; los tokens guardados dependen de ella. En otra instalación, genera una:

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Guarda ese valor en `.env` y conserva un respaldo seguro de la clave separado de
PostgreSQL. El archivo `.env.example` contiene campos vacíos, nunca claves reales.

6. Reinicia Django para que lea `.env`. Abre la aplicación en **127.0.0.1**, igual
   que la URI registrada. Cambiar a `localhost` durante el proceso puede perder
   la sesión; si eliges usar localhost, cambia y registra la URI exacta en ambos lugares.
7. En Salón HM entra a **Calendario → Conectar cuenta de Google**, selecciona el
   Gmail de Marisol y autoriza los permisos.
8. En [Google Calendar](https://calendar.google.com/), crea un calendario adicional
   llamado **Salón HM** si todavía no existe. Vuelve a la aplicación, selecciona
   ese calendario y pulsa **Usar este calendario**.
9. Crea una cita de prueba. En su detalle revisa que diga **Sincronizada** y confirma
   que aparezca en el calendario elegido. Las citas locales anteriores se pueden
   publicar con **Sincronizar con Google** en cada cita.

Si Google devuelve `redirect_uri_mismatch`, verifica la URI exacta, incluido el
puerto y la barra final. Si no permite autorizar, comprueba el usuario de prueba,
que la API esté habilitada y que los permisos de calendario se hayan concedido.
Los permisos y la habilitación de la API son pasos distintos: aceptar todas las
casillas no activa Google Calendar API en el proyecto. Si está deshabilitada,
abre [Google Calendar API en Google Cloud](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com),
selecciona el mismo proyecto del cliente OAuth y pulsa **Habilitar**. Después
vuelve a conectar desde Salón HM. El sistema distingue este error de permisos
insuficientes, autorización vencida y límites temporales de solicitudes.
La aplicación permite reconectar si la autorización caduca o es revocada.
Las restricciones del modo de pruebas deben revisarse antes de usarla continuamente.

## Permisos y datos

Se piden estos permisos, sin acceso a correo ni contactos:

- `calendar.events.owned`: gestionar eventos en calendarios propios.
- `calendar.calendarlist.readonly`: listar los calendarios para elegir uno.
- `calendar.freebusy`: consultar la ocupación del calendario personal.

La app permite elegir solo calendarios propios. Los eventos publicados contienen
el nombre de la clienta y el servicio previsto, por ejemplo `Ana López · Corte de dama`,
además del horario. El servicio aparece también en la descripción. No incluyen
teléfonos, notas privadas, fórmulas, costos ni historial. No se añaden invitados ni
se envían invitaciones. Se deshabilitan recordatorios predeterminados del evento.

Los tokens OAuth se cifran antes de guardarse en PostgreSQL. El proceso verifica
state, sesión, usuario, expiración y PKCE. Los parámetros del callback se ocultan
en el log de acceso de Django. En producción debe mantenerse esta protección en
el proxy y usar HTTPS con otra URI autorizada.

## Fallos y cambios externos

Primero se guarda la cita local y su trabajo de sincronización dentro de una
transacción. La llamada a Google ocurre después; un fallo no revierte la cita.
El identificador del evento se reserva antes de llamar a Google y se reutiliza en
reintentos para evitar duplicados. Las versiones locales obsoletas se descartan.
Los trabajos tienen bloqueo temporal y un máximo de cinco intentos automáticos.

Al eliminar en Google un evento publicado por el salón, la agenda confirma su
eliminación por ID y retira la cita de las vistas activas. Una cita pendiente o
confirmada pasa a Cancelada. Una atención ya realizada conserva su estado,
registro e historial. El cambio queda auditado y los trabajos pendientes se
anulan para no volver a publicar el evento. Se comprueba al abrir o actualizar
la agenda, incluida su actualización automática cada minuto mientras está visible.
Un evento movido fuera del intervalo, un error de Google o una cita todavía no
publicada no se interpretan como eliminaciones. La comprobación respeta la
cuenta, calendario y versión de la cita para no revertir cambios más recientes.

Las citas se envían al guardar si hay conexión. Si falla, el detalle muestra el error
y permite reintentar. Para procesar trabajos pendientes automáticamente, abre otra
terminal en el proyecto y ejecuta:

```powershell
.\.venv\Scripts\python.exe manage.py sincronizar_calendario --continuo
```

También puedes iniciar el servidor y el procesador juntos desde la raíz del proyecto:

```powershell
.\scripts\iniciar-local.ps1
```

El comando evita iniciar procesos duplicados y los abre en segundo plano. Los logs
quedan en `.tools`. Ejecuta este comando al volver a encender la computadora;
el procesador local necesita que esté encendida. No instala un servicio de Windows.

Sin `--continuo`, procesa un lote y termina. En producción este proceso se ejecutará
como worker del mismo proyecto; no requiere Redis ni Celery.

## Ver los eventos que ya estaban en Google

La agenda de **Día**, **Semana** y **Próximas**, y **Citas de hoy** en Inicio,
consultan los eventos del calendario elegido además de las citas del salón.
**Próximas** muestra los siguientes 30 días. Los eventos externos aparecen con
su título, horario y la etiqueta **Google Calendar**, con un enlace para abrirlos
en Google. Se consultan al abrir la página y automáticamente cada minuto mientras
la pestaña esté visible. Al regresar a la pestaña se consultan de nuevo. **Actualizar
ahora** permite hacerlo sin esperar. Solo cambia la lista de citas: conserva la
fecha y vista elegidas y no modifica formularios que estés llenando.
No se crean clientas ni visitas a partir de los eventos externos.

Las citas creadas en Salón HM se envían al guardarlas. Si falla el envío, el
procesador vuelve a intentarlo con pausas crecientes, hasta cinco intentos. Si
Google cambió un evento vinculado, se conserva el flujo de revisión del conflicto.

Se expanden las citas recurrentes y se respetan zona horaria, eventos de todo el
día y fecha final exclusiva. Una cita ya publicada desde el salón se muestra una
sola vez si tiene el mismo horario en ambos lugares. Si Google cambió el horario,
su evento también aparece para que puedas revisar la diferencia.

Solo se consultan títulos del calendario elegido. Otros calendarios personales
siguen aportando únicamente ocupaciones al comprobar disponibilidad. Si el
calendario elegido es el principal, sus eventos aparecerán en la agenda.
Un fallo de Google conserva las citas locales y muestra una advertencia;
el sistema no presenta la consulta fallida como una agenda completa vacía.

Los cambios hechos directamente en Google se detectan al comprobar/sincronizar o
al revisar un conflicto. No hay importación automática ni sincronización bidireccional.
Si el evento cambió, se muestra **Cambio externo en Google**; la pantalla permite
comparar horarios. Puedes editar la cita local con el horario de Google o confirmar
explícitamente reemplazar el evento con la versión del salón. La confirmación está
vinculada a la versión local, etag externo, usuaria y sesión. Los cambios posteriores
invalidan la confirmación. Una eliminación externa tampoco borra la cita local.

Los traslapes locales o externos requieren aceptar la advertencia del horario exacto.
Si no se puede consultar Google, se indica que su disponibilidad no fue comprobada,
y se permite guardar la cita local.

## Validación pendiente

Se prueban el flujo de autorización, cifrado, reintentos, conflictos y fallos con
pruebas del backend y dobles de Google. Las 135 pruebas Django pasan, incluidas
10 de consulta de eventos en la agenda. El 8 de octubre de 2026 se comprobó la
conexión real de Marisol y la visualización del evento **Doña lurdes**, del 10 de
octubre, de 15:00 a 16:00, en Día, Semana y Próximas, en Chrome móvil y escritorio.

Referencias oficiales:

- [OAuth para aplicaciones web](https://developers.google.com/identity/protocols/oauth2/web-server).
- [Permisos de Calendar](https://developers.google.com/workspace/calendar/api/auth).
- [Creación de eventos](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert).
- [Modificaciones condicionales con etag](https://developers.google.com/workspace/calendar/api/guides/version-resources).
