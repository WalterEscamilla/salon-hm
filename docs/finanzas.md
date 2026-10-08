# Finanzas del salón

La base de **$10,000 MXN** representa dinero disponible, no un gasto ni una ganancia.
La migración crea la base con la fecha local del salón al instalar esta sección.
En **Finanzas → Editar saldo inicial** Marisol puede revisar el importe y el día
desde el que se contarán los movimientos. El día de inicio se incluye completo;
los registros anteriores siguen en el historial y no cambian el saldo.

## Registrar gastos

En **Finanzas → Registrar gasto**, captura fecha de pago, concepto, categoría,
importe y notas opcionales. Por ejemplo, luz semanal por $200 o una lámpara nueva.
Cada pago se registra cuando ocurre; escribir «semanal» no crea gastos automáticos.
Comprar materiales no cambia automáticamente el inventario: el conteo sigue manual.

Los gastos pueden corregirse. Al anular uno, se exige motivo, se conserva el
historial y deja de descontarse del saldo. Los envíos duplicados no duplican pagos.
«Ver todos los gastos» también permite consultar y corregir pagos anteriores al inicio.

## Registrar cada servicio

- **Precio cobrado:** dinero recibido por esa visita, incluido cualquier descuento.
- **Costo de materiales utilizados:** valor de lo consumido, incluso si se compró antes.
- **Otros gastos:** costo adicional atribuible a la visita; el pago general de luz
  de toda la semana se registra en Gastos.
- **Estos gastos se pagaron ahora y no están registrados en Gastos:** solo se marca
  si **ambos** costos se pagaron durante esa visita y aún no aparecen como gastos.

Si parte de los materiales estaba comprada y solo se hizo un pago adicional,
deja la casilla sin marcar y registra únicamente ese pago adicional en Gastos.
Si un importe no se conoce, déjalo vacío. Escribe **0** cuando no hubo ese costo.
Para descontar costos directamente de la visita, ambos importes deben estar completos.

El formulario muestra costo total y margen antes de guardar. La IA separa precio,
materiales y otros gastos; Marisol revisa el resultado. La casilla que descuenta
dinero se conserva según la selección humana y no la decide la IA.
Corregir una visita recalcula los totales; no crea un segundo movimiento.

## Cómo se calcula

**Saldo = base + precios cobrados − gastos vigentes − costos de visitas marcados como pagados.**

**Margen de una visita = precio cobrado − materiales utilizados − otros gastos de esa visita.**

El margen se calcula solo cuando se conocen los tres importes. No es utilidad
neta del salón: no incluye por separado renta, equipo u otros gastos generales.
La pantalla indica cuántas visitas tienen importes completos y cuáles carecen de precio.
No se convierte un dato desconocido en cero ni se presupone crédito o pagos pendientes.

Ejemplo ficticio: base $10,000, luz pagada $200 y una visita cobrada en $500.
Usó $80 en materiales comprados antes y no hubo otros gastos ($0).
Su margen es $420, y el saldo es $10,300. Los $80 no se descuentan otra vez.
Si esos $80 se compraron y pagaron en esa visita, se marca la casilla y el saldo
es $10,220; no se registra después otro gasto por los mismos $80.

Los servicios históricos conservan sus precios. Sus nuevos campos de costo quedan
vacíos; sus pagos solo participan si su fecha está dentro del período configurado.
Los importes no se envían a Google Calendar.

## Publicar en Railway

Este cambio agrega tablas de Finanzas y columnas opcionales a las visitas existentes.
Antes de enviar el código, verifica en el servicio web **salon-hm → Settings → Deploy
→ Pre-deploy command** el comando `python manage.py migrate --noinput`.
El servicio web aplicará las migraciones antes de iniciar la nueva versión.
El worker conserva `python manage.py sincronizar_calendario --continuo` como inicio.
No ejecutes una nueva importación del respaldo sobre la base de producción.

La extracción usa campos opcionales con `null` y validación de importes en el servidor,
siguiendo [Function calling de OpenAI](https://developers.openai.com/api/docs/guides/function-calling).
