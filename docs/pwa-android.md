# Instalar Salón HM en Android

Esta versión permite instalar la aplicación desde Chrome con el nombre **Salón HM**,
el icono HM con corona y una ventana propia. La agenda, el historial, los gastos y
el asistente siguen usando internet. No se requiere una cuenta de Google Play.

## Publicación e instalación

1. Publicar los cambios en Railway después de aprobar la versión local.
   Este cambio no requiere migraciones ni nuevas variables en `.env`.
2. En el Android de Marisol, abrir **Google Chrome** y entrar a
   `https://salon-hm-production.up.railway.app/`.
3. Iniciar sesión con la cuenta habitual.
4. Si aparece **Instalar app**, pulsarlo y confirmar la instalación que muestra Chrome.
   Si no aparece, abrir el menú de los tres puntos y buscar **Instalar app** o
   **Añadir a pantalla de inicio**; el texto puede variar según la versión.
5. Abrir **Salón HM** desde su icono y comprobar el acceso y la agenda.

El botón del salón aparece cuando Chrome comunica que puede instalar la aplicación;
puede tardar en aparecer y se oculta cuando la ventana ya está en modo aplicación.
No se instala automáticamente. Si Marisol cancela, el salón sigue funcionando en Chrome.
La sesión puede pedir acceso otra vez según la configuración del navegador.

## Si se pierde la conexión

La aplicación muestra un aviso para conectarse antes de continuar. Si ya sabe que
el teléfono está sin conexión, detiene el envío del formulario y conserva lo escrito
en la página actual. Al reconectarse, Marisol debe pulsar Guardar nuevamente.
Si la conexión falla mientras se envía una operación, hay que revisar el historial
al volver; el aviso no confirma si el servidor alcanzó a guardarla.

Al abrir una página sin internet aparece **Sin conexión** y **Volver a intentar**.
El service worker conserva solo esa página pública. No guarda agenda, clientas,
servicios, gastos, respuestas del asistente ni páginas de acceso en su caché.
No crea una cola de registros ni reenvía operaciones automáticamente.

## Archivos y verificación

- `/manifest.webmanifest`: nombre, ventana, colores e iconos.
- `/service-worker.js`: pantalla genérica al fallar una navegación en línea.
- `/sin-conexion/`: página pública sin datos de usuario, tokens ni recursos externos.
- `static/img/pwa/`: PNG de 192 y 512 píxeles y un icono adaptable para Android,
  derivados del SVG actual.
- `static/js/pwa.js`: instalación con confirmación del navegador y aviso de conexión.

Las URLs de instalación son públicas; las páginas del salón conservan el acceso privado.
El worker se actualiza sin recargar automáticamente formularios abiertos. Los cambios
de versión podrán activarse al cerrar y volver a abrir la aplicación.

En desarrollo, Chrome acepta `http://127.0.0.1` para las comprobaciones locales.
La prueba final de instalación en Android se realiza con el dominio HTTPS de Railway;
`127.0.0.1` en el celular apunta al propio celular, no a la PC.

Verificación local del 9 de octubre de 2026: 234 pruebas de Django aprobadas;
Chrome reconoció el manifest y emitió la oferta de instalación. Se comprobó
el botón con un evento simulado, el aviso sin conexión, la conservación del
formulario, el acceso y cierre de sesión, y diseños de 320, 390 y 1280 píxeles.
La caché del worker contenía únicamente `/sin-conexion/`. El build de producción
sirvió los iconos, CSS y JavaScript con WhiteNoise. La instalación real en el
Android de Marisol queda para la comprobación posterior a publicar.

Fuentes oficiales: [manifest y criterios de instalación](https://web.dev/articles/install-criteria),
[instalación en Chrome](https://developer.chrome.com/blog/update-install-criteria) y
[pantalla al fallar la conexión](https://web.dev/articles/offline-fallback-page).
