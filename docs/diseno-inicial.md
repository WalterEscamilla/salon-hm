# Salón HM: propuesta de diseño inicial

Estado: alcance aclarado; etapa 1 en implementación local, sin despliegue.
Fecha: 7 de octubre de 2026.

## 1. Negocio y alcance

Aplicación privada para que la administradora gestione desde el celular clientes,
citas, atenciones realizadas, fórmulas, consumo de materiales y pagos.
La agenda describe lo previsto; una atención describe lo que realmente ocurrió.
El historial debe conservar lo registrado aunque cambien los catálogos.

MVP completo, entregado por etapas:

- Acceso autenticado, sin registro público; un salón y una administradora.
- Interfaz en español, MXN y zona configurable, inicialmente America/Merida.
- Clientes con búsqueda, archivo e historial; se permiten nombres repetidos.
- Servicios y productos, con precios, duraciones, unidades y costos opcionales.
- Atenciones con varios servicios, fórmulas, consumos, descuento y pagos parciales.
- Anticipos ocasionales de citas, aplicados posteriormente a la atención sin duplicar ingresos.
- Agenda de día, semana y próximas citas, estados y advertencias de traslapes.
- Google Calendar: publicación de citas locales, ocupaciones, reintentos y conflictos.
- Asistente de consultas y preparación de operaciones con confirmación humana.
- Auditoría, controles de seguridad, pruebas críticas y despliegue documentado.

Posteriormente: inventario y compras, personal con agendas propias, sincronización
bidireccional completa, API pública y aplicación móvil nativa. Facturación fiscal,
mensajería y cobro con tarjeta mediante una pasarela quedan fuera del alcance inicial.

Alcance confirmado: generalmente una clienta a la vez, con traslapes aceptables
en casos especiales tras una advertencia y aceptación explícita. Se reciben anticipos
ocasionales, por lo que pertenecen al MVP. El historial existente se compartirá después;
su importación se diseñará al conocer el formato, sin retrasar la base local.
Métodos iniciales de pago: efectivo, transferencia y tarjeta como registro manual.
La aplicación requiere internet; la independencia de Google/OpenAI no implica uso offline.

## 2. Arquitectura

Monolito modular: Python 3.13, Django 5.2 LTS con parche vigente, PostgreSQL 17,
templates de Django, HTMX 2 y Bootstrap 5. Los parches y SDK se fijarán al iniciar
la implementación, después de comprobar compatibilidad y documentación oficial.
Django 5.2 admite Python 3.13 y recibe soporte extendido hasta abril de 2028.

Módulos propuestos:

- cuentas: usuario propio basado en AbstractUser desde la primera migración.
- configuracion: nombre, moneda y zona del salón, sin estructura multinegocio.
- clientes: búsqueda, edición, archivo e historial.
- catalogos: servicios y productos.
- agenda: citas y servicios previstos.
- atenciones: servicios realizados, consumos, cálculos y pagos.
- integraciones: adaptadores de Google Calendar y OpenAI.
- asistente: herramientas, conversación y borradores.
- auditoria: operaciones relevantes y su origen.

Cada módulo separa modelos, formularios/vistas, consultas y servicios de negocio.
Los formularios y las herramientas del asistente llaman a los mismos servicios.
Solo esos servicios realizan escrituras; validan permisos y reglas y usan el ORM.
Los adaptadores externos no calculan importes ni deciden autorizaciones.
Así una futura API podrá reutilizar las operaciones existentes.

Desarrollo: Docker Compose con aplicación y PostgreSQL. Un proceso del mismo
código ejecutará la cola persistente de sincronización cuando se incorpore Google.
Sin Redis ni Celery inicialmente: los trabajos estarán en PostgreSQL y un comando
de Django los procesará con bloqueo, arrendamiento temporal y reintentos limitados.
Las peticiones web guardarán primero la operación local y el trabajo en una misma
transacción; las llamadas a Google ocurrirán fuera de esa transacción.

Producción prevista: Railway, Gunicorn, estáticos servidos con WhiteNoise,
migraciones antes del arranque y health check. Esto es un destino de diseño;
la configuración real y su documentación oficial se verificarán en la etapa de despliegue.

## 3. Modelo inicial

Todas las entidades tienen clave propia; los nombres son datos, no identificadores.
Las fechas de operaciones son conscientes de zona horaria y se almacenan en UTC.
Las fechas locales de reportes se convierten a intervalos UTC antes de consultar.

| Entidad | Datos y relaciones principales |
| --- | --- |
| Usuario | Credenciales Django, activo y permisos. Autor de operaciones; permite incorporar personal posteriormente. |
| ConfiguracionSalon | Única fila: nombre, MXN, America/Merida configurable. |
| Cliente | Nombre, teléfono opcional, teléfono normalizado, notas y fecha de archivo. Tiene muchas citas y atenciones. |
| Servicio | Nombre, descripción, duración estimada, precio base y activo. |
| Producto | Nombre, marca, línea, tono, presentación, contenido, unidad g/ml/unidad, costo de compra y costo de consumo opcionales; activo. |
| Cita | Cliente, inicio, fin, notas, estado, responsable y versión. No contiene importes realizados. |
| ServicioPrevisto | Relación Cita–Servicio, nombre y duración previstos copiados al agendar. |
| Atencion | Cliente, cita opcional, fecha, responsable, notas, subtotal, descuento, total, estado vigente/anulada y versión. Inicialmente máximo una atención por cita. |
| ServicioRealizado | Relación Atención–Servicio; conserva nombre, precio base de referencia, precio aplicado y observaciones. Cada fila representa un servicio realizado. |
| ConsumoProducto | Servicio realizado, producto, nombre/marca/tono copiados, cantidad, unidad, costo unitario aplicado nullable y observaciones de fórmula. |
| Pago | Cliente, origen cita o atención, importe, método, fecha efectiva y autor. Un anticipo conserva su fecha y origen originales. |
| AplicacionPago | Pago, atención e importe aplicado; vincula anticipos con la atención sin crear otro pago. |
| ConexionGoogle | Usuario, calendario elegido, scopes, tokens cifrados, expiración y estado de autorización. |
| TrabajoSincronizacion | Cita, conexión, versión local, operación, intentos, próxima ejecución, bloqueo temporal, estado y error resumido. |
| VinculoEventoGoogle | Cita, conexión/calendario, identificador de evento, etag y última versión sincronizada. Conserva el identificador para reintentos. |
| BorradorOperacion | UUID, tipo, payload validado, versión/hash, usuario, sesión, expiración, estado y referencia al resultado. |
| Auditoria | Actor, fecha, origen formulario/asistente/sistema, operación, entidad, identificador y cambios necesarios. |

Las relaciones históricas con clientes, servicios y productos usan PROTECT.
Los catálogos se desactivan y los clientes se archivan, conservando sus relaciones.
Las fórmulas son el conjunto de consumos y observaciones de un servicio realizado;
no hace falta todavía un catálogo independiente de recetas.

Restricciones propuestas:

- Fin de cita posterior al inicio; duración y contenido de presentación positivos.
- Importes y costos no negativos, consumos positivos y pagos positivos.
- Descuento entre cero y subtotal; total = subtotal - descuento.
- Unidad de consumo compatible con el producto, validada por el servicio de negocio.
- Costos desconocidos como NULL. No convertir g a ml sin conversión explícita.
- Un pago nace de una cita o una atención, exactamente uno de estos orígenes.
- Aplicaciones del mismo cliente; su suma no supera el pago ni el total de la atención, con bloqueos transaccionales.
- Una configuración; vínculo Google único por cita y conexión, y evento único por calendario.
- Trabajo único por cita, conexión, versión y operación; clave idempotente única para cada escritura.
- Un borrador consumido solo puede devolver su resultado original.

Las reglas entre varias filas se aplican dentro de transacciones con bloqueos,
no mediante CHECK que intente consultar otras tablas. Las reglas de una fila y
las unicidades también se expresan como restricciones de PostgreSQL.

Índices iniciales: cliente por teléfono normalizado; atención por cliente y fecha;
cita por responsable e inicio, y por estado e inicio; pago por fecha efectiva;
trabajo por estado y próxima ejecución; auditoría por entidad/identificador/fecha.
La búsqueda por fragmentos usa icontains; un B-tree normal no acelera ese caso.
Se evaluará pg_trgm únicamente si el volumen medido lo necesita.

Dinero: Decimal/NUMERIC con dos decimales; cantidades y costos unitarios con
precisión adicional. Política propuesta: seis decimales para costos unitarios y
cantidades, redondeo explícito a centavos de cada costo de consumo y suma de líneas.
Saldo se deriva del total menos aplicaciones de pagos vigentes para evitar duplicar estado.

## 4. Reglas verificables

Ejemplo: atención de $850, pago recibido de $500, saldo de $350.
El total de servicios se reporta por fecha de atención; los pagos, por fecha efectiva.
"Le cobré $850" registra precio; no crea un pago sin evidencia de que se recibió.
Cambiar posteriormente el precio del tinte o su costo no cambia esta atención.

Un anticipo recibido el lunes y aplicado a una atención el viernes cuenta como ingreso
del lunes. Aplicarlo no crea un segundo ingreso el viernes. No crea una atención ficticia.
Si se cancela la cita, el anticipo queda pendiente de resolución explícita: saldo a favor
o devolución registrada con su fecha e importe. Cancelar no elimina un dinero recibido.
La devolución tendrá un registro separado y auditable; los reportes distinguirán pagos
recibidos, devoluciones e importe neto recibido. Se validará que las devoluciones y
aplicaciones no excedan el pago original.

Si un consumo tiene costo desconocido, el costo total es incompleto. Puede mostrarse
la suma conocida, etiquetada como parcial; no se muestra un margen completo.
Con todos los costos conocidos, margen sobre materiales = total - costo de materiales.
Nunca se presenta como utilidad neta.

Completar una cita no crea atención, pagos ni consumos. El formulario permite abrir
una atención desde la cita y revisar los datos reales antes de guardar.
Anulaciones y correcciones son explícitas y auditadas, sin borrado definitivo por chat.
Si existen pagos, una anulación exige resolverlos explícitamente; no se inventa devolución.

## 5. Google Calendar

OAuth 2.0 de aplicación web, con state vinculado a la sesión y URI de retorno registrada.
Elegir calendario dedicado; permisos mínimos compatibles con listar calendarios,
gestionar eventos propios del calendario elegido y consultar ocupaciones autorizadas.
Los scopes concretos se comprobarán al implementar el flujo.
Refresh tokens cifrados con clave separada de la base; documentar rotación y restauración.

Publicar solo horario, referencia y descripción mínima de cita. Por defecto usar
referencia de cita en el título, sin teléfono, notas privadas, fórmulas ni costos.
Sin asistentes/invitados y con sendUpdates=none para evitar notificaciones automáticas.
Las ocupaciones personales consultadas solo alimentan advertencias de disponibilidad.
Si Google falla, guardar localmente y mostrar que la disponibilidad externa no se verificó.

Usar un ID de evento válido y determinista derivado de la cita para crear y reintentar.
Si ya existe, verificar el vínculo antes de tratarlo como creación completada.
El procesador comprueba la versión local antes de publicar y descarta trabajos obsoletos.
Updates y cancelaciones usan etag/If-Match; un cambio externo produce conflicto visible,
sin sobreescribirlo. Comparar también eventos vinculados al refrescar la agenda.
Una eliminación externa se muestra como conflicto, sin cancelar automáticamente la cita.
La administradora decide entre conservar Google ajustando la cita o volver a publicar
la versión local. La sincronización bidireccional automática se deja para otra fase.

## 6. Asistente

Responses API desde el servidor; OPENAI_MODEL configurable y herramientas con
strict=true. Las herramientas reciben esquemas cerrados, validan tipos, permisos,
identificadores, unidades e importes y devuelven resultados estructurados del ORM.
El modelo nunca recibe una conexión SQL ni una herramienta de SQL libre.

Herramientas de consulta: buscar_clientes, obtener_historial_cliente,
obtener_ultimo_servicio, buscar_servicios, buscar_productos,
consultar_disponibilidad y consultar_resumen_cobros.
Herramientas de preparación: preparar_registro_atencion y preparar_cita.
Confirmar_registro_atencion y confirmar_cita serán operaciones del backend sujetas
a una autorización humana registrada; el modelo no puede fabricar esa autorización.

Flujo: interpretar → resolver coincidencias/ambigüedades → preparar borrador →
mostrar resumen editable → clic humano de confirmación → transacción → resultado.
La confirmación usa POST con CSRF y vincula usuario, sesión, ID, versión/hash y
expiración del borrador. Editar el resumen invalida la confirmación anterior.
Antes de guardar se revalidan permisos y referencias y se bloquea el borrador.
Reintentos y doble clic devuelven el mismo resultado, sin nuevas escrituras.

"Hoy" se resuelve con reloj del servidor y zona configurada del salón. Si una fecha
explícita lo contradice, preguntar. Horas incompletas o ambiguas se aclaran.
Con clientes homónimos se muestran candidatos mínimos y se exige selección.
Las notas recuperadas son datos; no cambian instrucciones ni permisos del asistente.
Enviar únicamente los datos necesarios y limitar historial, llamadas por turno,
tiempos de espera y presupuesto configurable. Las claves permanecen en el servidor.

## 7. Entregas y validación

| Etapa | Resultado verificable |
| --- | --- |
| 0. Acordar diseño | Resolver las preguntas de alcance y aceptar este documento. |
| 1. Base local | Compose con PostgreSQL, proyecto modular, usuario propio, login privado, configuración, home móvil, .env.example y README. Migraciones y protección de rutas comprobadas. |
| 2. Clientes y catálogos | CRUD/archivo/desactivación y búsqueda; datos ficticios. Verificar homónimos y búsquedas sin resultados. |
| 3. Atenciones y pagos | Registrar varios servicios, fórmula y pagos; historial y cobros. Probar costos desconocidos, unidades, precios históricos, saldo y doble clic. |
| 4. Agenda local y anticipos | Día, semana y lista, estados y citas enlazables a atención. Registrar y aplicar anticipos. Probar zonas, aceptación de traslapes y aplicación sin duplicar ingresos. Completar no genera cobros. |
| 5. Google Calendar | OAuth, elección de calendario, ocupaciones, publicación y estados. Probar fallos, revocación, reintentos y cambios externos; validar además con cuenta real. |
| 6. Asistente | Consulta y preparación/confirmación. Probar ambigüedad, rechazo sin autorización, borrador editado/vencido, errores y reintentos; validar además con API real. |
| 7. Railway | Configuración reproducible, migraciones, estáticos, health check y manual operativo. Publicación tras autorización; respaldo y restauración comprobados. |

Cada etapa entrega código, migraciones necesarias, README actualizado y pruebas
de sus flujos críticos. La primera base funcional no equivale al MVP completo.
Las pruebas de integración con mocks se distinguirán de la validación con credenciales reales.

Seguridad transversal: autenticación en rutas, CSRF, cookies seguras bajo HTTPS,
secretos por entorno, DEBUG desactivado en producción, hosts autorizados, permisos
en todos los servicios y auditoría en la misma transacción que la escritura.
Logs sin tokens, prompts completos ni PII innecesaria.
Respaldo propuesto: diario cifrado, retención de 30 días y copia independiente;
restauración en una base aislada antes de uso real y comprobación periódica.
Respaldar también la clave de cifrado por separado; una copia de PostgreSQL sola
no recupera las conexiones Google cifradas. Objetivos iniciales: hasta 24 horas
de pérdida de datos y recuperación en una jornada, a revisar según uso y presupuesto.

## 8. Respuestas de alcance

1. Generalmente una clienta a la vez; varias en casos especiales.
2. Sí recibe anticipos ocasionalmente.
3. Existe historial y se compartirá más adelante por este chat.

## 9. Documentación oficial consultada

- [Versiones y soporte de Django](https://www.djangoproject.com/download/).
- [Compatibilidad Python/Django 5.2](https://docs.djangoproject.com/en/5.2/faq/install/).
- [PostgreSQL con Django](https://docs.djangoproject.com/en/5.2/ref/databases/#postgresql-notes).
- [OpenAI: function calling](https://developers.openai.com/api/docs/guides/function-calling).
- [Google: control de versiones y modificaciones condicionales](https://developers.google.com/workspace/calendar/api/guides/version-resources).
- [Google: creación de eventos](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert).
- [Google: consulta de disponibilidad](https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query).

Esta revisión valida decisiones de diseño, no una integración ejecutada. Las versiones
exactas y documentación de despliegue se revisarán nuevamente al implementar cada etapa.
