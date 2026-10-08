# Entrar a Salón HM con Google

La cuenta autorizada se configura en `GOOGLE_LOGIN_EMAIL` y se vincula con la usuaria existente
`Marisol`. Conserva el mismo identificador local, permisos, citas e historial.
No existe registro público de otras cuentas.

## Configuración

Usa el cliente OAuth de tipo **Aplicación web** existente. Para entrar se utiliza
la misma URI de retorno que Calendar; no hace falta registrar una segunda:

```text
http://127.0.0.1:8010/calendario/google/retorno/
```

Debe coincidir exactamente con `GOOGLE_REDIRECT_URI` en `.env` y con la dirección
autorizada en Google Cloud. Agrega el Gmail de Marisol como usuario de prueba.
Mantén las credenciales y estas opciones en `.env`:

```dotenv
GOOGLE_CLIENT_ID=ID_DEL_CLIENTE
GOOGLE_CLIENT_SECRET=SECRETO_DEL_CLIENTE
GOOGLE_REDIRECT_URI=http://127.0.0.1:8010/calendario/google/retorno/
GOOGLE_LOGIN_EMAIL=TU_CORREO_AUTORIZADO
GOOGLE_LOGIN_USERNAME=Marisol
```

Reinicia el servidor después de modificar `.env`. Usa `127.0.0.1` durante todo
el proceso; cambiar a `localhost` pierde la sesión que inició la autorización.

## Uso

1. Abre el salón y pulsa **Entrar con Google**.
2. Elige el correo autorizado y permite compartir la identidad y dirección de correo.
3. Al volver, verás **Hola, Marisol.** Puedes seguir entrando con usuario y contraseña.
4. Para sincronizar citas, abre **Inicio → Configurar calendario → Conectar cuenta
   de Google**. Autoriza los permisos de Calendar y elige el calendario del salón.
   Esta segunda autorización permite sincronizar incluso cuando Marisol no está conectada.

Entrar con Google obtiene su dirección de correo; no permite leer los mensajes
de Gmail. La integración de Gmail requiere definir qué mensajes se necesitan y
añadir sus permisos y funcionalidades.

## Protección y validación

Se utiliza el flujo de código en el servidor con PKCE, state de sesión y nonce,
con vencimiento de diez minutos. La biblioteca oficial valida la firma, emisor,
audiencia y vencimiento del ID token. Además se comprueba el correo verificado,
nonce, cuenta permitida y que la usuaria local esté activa.

La primera autorización guarda el identificador estable de Google (`sub`), único
en la base. Las siguientes deben corresponder a esa misma identidad. Cambiar
solo el correo en `.env` no reemplaza una identidad ya vinculada.
El inicio rota la sesión y queda auditado. Los códigos y parámetros del retorno
se ocultan en el log de desarrollo; en producción debe protegerse también el proxy.
Los tokens del inicio de sesión no se conservan. Calendar guarda sus propios tokens cifrados.

Las 119 pruebas Django pasan, incluidas 22 de acceso con Google. Cubren otra
cuenta, firma rechazada por el verificador, nonce, state, sesiones distintas,
caducidad, repetición, cuenta inactiva, vinculación estable, CSRF y rollback.
La autorización real requiere que Marisol complete el proceso en su navegador.

Si Google muestra `redirect_uri_mismatch`, abre **Google Auth Platform → Clientes**,
selecciona el cliente cuyo ID guardaste en `.env` y añade la URI exacta de arriba
en **URI de redirección autorizados**, no en orígenes JavaScript. Guarda el cambio
y vuelve a intentar; los cambios pueden tardar en propagarse.

Referencias: [OpenID Connect de Google](https://developers.google.com/identity/openid-connect/openid-connect)
y [validación oficial de ID tokens en Python](https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.id_token.html).
