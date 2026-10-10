# Asistente, historial de clientas y productos

Desde el menú **Asistente**, describe lo que quieres registrar. OpenAI puede buscar
clientas e historial, registrar visitas realizadas, consultar catálogo e inventario y preparar propuestas.
También está disponible arriba de **Registrar servicio**: escribe la descripción
y pulsa **Completar con IA** para llenar el formulario de abajo sin salir de la página.
Puedes ajustar los campos y pulsar **Guardar servicio**. Cuando el formulario viene
de la agenda, conserva el evento y lo marca como Hecho después del guardado.
Para una visita realizada, el asistente abre directamente un **formulario editable**.
Corrige los datos y pulsa **Guardar servicio**; no hay un resumen intermedio. Los datos
obligatorios que falten y las dudas aparecen arriba para aclararlos en ese formulario.
Si hay nombres iguales, ahí mismo puedes elegir a la clienta correcta. Precio y
duración pueden variar: el precio pertenece a esa visita y la duración no es obligatoria.
Una visita antigua sin fecha exacta queda con la fecha vacía hasta que la completes.

Puedes recuperar un formulario desde **Registros pendientes → Abrir formulario**.
Para catálogo e inventario, abre la propuesta, comprueba el resumen y pulsa
**Confirmar y guardar**. Si modificas esos campos, pulsa **Actualizar propuesta** y
revisa el nuevo resumen antes de confirmar. Escribir “sí” en el chat no guarda datos.

Ejemplos:

- “Hoy atendí a Ana López, teléfono 9991234567. Le hice corte, cobré $200 con descuento y usé champú.”
- “¿Qué le hice a Ana López la última vez?”
- “Agrega corte de cabello por $250, duración 45 minutos.”
- “Crea un producto peróxido marca Ejemplo, unidad ml, envase de 1000 ml y costo $120.”
- “Registra peróxido de 30 volúmenes Kuul: cada botella trae 870 ml, cuesta $65,
  tengo 3.5 botellas y quiero aviso cuando quede una.” El asistente abre la propuesta
  del producto con stock y aviso mínimo expresados en botellas.
- “Descuenta 35 ml de ese producto, motivo: consumo de hoy.”
- “Al contar físicamente quedan 780 ml; prepara un ajuste con motivo: conteo físico.”
- “¿Qué productos tienen stock bajo?”

También puedes usar **Inicio → Servicios** y **Productos → Nuevo producto**. Dentro
del producto, **Registrar movimiento** permite agregar o descontar existencias sin IA.

## Configuración

En `.env`:

```dotenv
OPENAI_API_KEY=tu_clave
OPENAI_MODEL=gpt-5.4-mini
OPENAI_DAILY_REQUEST_LIMIT=60
```

Conserva el resto de tus variables. Reinicia Django si cambias `.env`.
La clave se utiliza solo en el servidor y no aparece en las páginas. El modelo es
configurable. La integración usa el SDK oficial y Responses API, herramientas con
esquemas estrictos y `store=False`. Esto desactiva el almacenamiento de la respuesta
para recuperarla mediante la API; no equivale a una política de retención cero.
La API utiliza la facturación del proyecto OpenAI, independiente de una suscripción
de ChatGPT. El sitio informa que el mensaje y los datos necesarios se envían a OpenAI.

El asistente recibe hasta 12 mensajes recientes, resultados limitados del catálogo,
coincidencias de clientas, hasta ocho visitas de la persona consultada y estado de propuestas.
No recibe notas de citas, credenciales, tokens Google ni el historial completo de la base. El historial del chat y las
propuestas se conservan en PostgreSQL; una nueva sesión tiene una conversación nueva.

Límites: 4000 caracteres por mensaje, 4 mensajes por minuto por usuaria, 60 solicitudes
por 24 horas de manera predeterminada, 6 llamadas a Responses por turno, 8 herramientas
y 3 borradores por turno, 20 borradores pendientes y 1800 tokens de salida por llamada.
Cada llamada tiene timeout de 25 segundos sin reintentos automáticos. Estos límites
controlan el uso; no representan un límite de gasto monetario en OpenAI.

## Reglas de inventario

- Cada producto tiene una presentación (Botellas, Tubos u otra) y una unidad del
  contenido (ml, l, g, unidad u otra). Puedes escribir nuevas opciones; se conservan
  al guardar el producto. No se convierten unidades de contenido distintas entre sí.
  Los movimientos en la unidad **unidad** necesitan cantidades enteras.
- Al crear un producto, el conteo inicial y el aviso mínimo se expresan en su
  presentación. El servidor convierte ambos usando el contenido de una presentación.
  Si dejas el conteo vacío, comienza con
  existencias cero y el conteo queda pendiente. El conteo inicial es un ajuste
  auditado, conserva el saldo financiero y no registra una compra.
  Consulta la [guía del conteo inicial](conteo-inicial-inventario.md).
- Entrada agrega cantidad; salida la descuenta; ajuste fija el conteo final indicado.
- Los movimientos requieren motivo. No se permiten existencias negativas.
- El costo puede quedar desconocido (NULL). Cero significa costo conocido de cero.
  El costo por unidad se calcula solo si se conocen costo y contenido del envase.
- Los movimientos conservan el costo y la unidad de su momento. Cambiar el costo
  del catálogo no modifica el historial. Esto aún no es valuación FIFO o promedio.
- Un producto con movimientos conserva su presentación, contenido y unidad. Crea
  un producto distinto si necesitas otra presentación. Productos pueden desactivarse.
- El stock bajo compara existencias con el mínimo elegido. No compra automáticamente.
- Consumos son movimientos manuales independientes; no están vinculados todavía
  a atenciones o fórmulas, y agendar/finalizar una cita no descuenta productos.

## Confirmación y concurrencia

OpenAI no tiene herramientas de SQL, ejecución de código, eliminación o confirmación.
Las herramientas de escritura solamente crean borradores. El guardado humano es un POST
con CSRF desde el formulario privado; exige permisos de negocio, misma usuaria y sesión,
versión y huella exacta del borrador. Para visitas, ese POST valida las correcciones
del formulario y guarda clienta, servicio y auditoría juntos. El borrador conserva la
interpretación original y el historial conserva los datos aprobados. Las propuestas
vencen a los 30 minutos.
Si el catálogo o stock cambian después de preparar la propuesta, debe prepararse otra.

Confirmar dos veces devuelve el resultado existente. Los movimientos incluyen una
clave idempotente. El alta del producto y su conteo inicial también comparten una
clave para evitar duplicarlos al reenviar el mismo formulario.
Transacciones y bloqueos de filas serializan los cambios de stock;
la revisión de versión impide que dos ventanas descuenten sobre un saldo desactualizado.
Auditoría y datos se guardan en la misma transacción. Los mensajes de errores de OpenAI
no muestran claves ni cuerpos de error del proveedor.

## Validación de esta entrega

La actualización por presentaciones pasó las 267 pruebas Django. Chrome verificó
la captura de 3.5 botellas de 870 ml con aviso de una botella, tubos de 90 g y una
presentación y unidad personalizadas. Las pruebas se ejecutaron sobre PostgreSQL
temporal; las respuestas de OpenAI se simularon y no se guardaron ejemplos en producción.

La verificación anterior del conteo inicial fue:

La actualización del conteo inicial pasó la suite completa de 254 pruebas Django.
Chrome verificó el alta manual y por asistente, recuperación del contenido faltante,
conversión de 3.5 botellas de 875 ml a 3062.5 ml, enlaces inválidos y formularios a
320, 390 y 1280 píxeles. Estas comprobaciones usaron PostgreSQL temporal y respuestas
controladas de OpenAI; no agregaron productos ficticios a la base del salón.

Las verificaciones siguientes corresponden a entregas anteriores:

188 pruebas Django en PostgreSQL separado, incluidas 14 del asistente dentro de
Registrar servicio y 17 del formulario directo de propuestas. Incluyen
confirmación, CSRF, edición de propuestas, permisos, expiración, idempotencia,
rollback de auditoría, costos históricos, unidades, stock negativo, concurrencia,
errores externos, presupuesto de llamadas y esquemas estrictos. El ciclo de
herramientas se prueba con respuestas controladas.

Además se comprobó una llamada real a OpenAI con datos ficticios y los mismos
esquemas: respondió con `preparar_servicio` y estado `completed`. Después se probó
el ciclo completo real para servicio, producto y entrada de stock sobre una base
temporal separada. Se verificaron los borradores antes de confirmar, selección
por ID, conversión de dos envases de 1000 ml a 2000 ml y confirmación HTTP.
La base temporal se eliminó al terminar; el catálogo real no recibió registros ficticios.
Chrome comprobó agenda, productos, nuevo producto y asistente en móvil/escritorio.
El flujo de servicios realizados también se comprobó con OpenAI real en una base temporal:
búsqueda de clienta, salto directo al formulario, corrección del precio, guardado HTTP
en un paso con CSRF y consulta de la última atención con el precio corregido y materiales.
Se verificaron avisos arriba y fecha/precio desconocidos sin inventar datos. Chrome
comprobó el formulario editable a 320, 390 y 1280 píxeles. Consulta
la [guía de registro diario](registro-diario.md) para el uso actual.

Referencias oficiales:

- [Function calling](https://developers.openai.com/api/docs/guides/function-calling).
- [Modelo GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
- [Uso y retención de datos](https://developers.openai.com/api/docs/guides/your-data).
