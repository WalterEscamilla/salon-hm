# Registrar los productos que ya tienes

Entra a **Productos → Nuevo producto**. Para el ejemplo de Marisol, completa:

| Campo | Valor |
| --- | --- |
| Nombre | Peróxido 30 vol |
| Presentación | Botellas |
| Contenido por presentación | 870 |
| Unidad del contenido | ml |
| Precio por presentación (MXN) | 65 |
| Stock inicial (presentaciones) | 3.5 |
| Avisar cuando queden (presentaciones) | 1 |

Pulsa **Guardar producto**. La lista y el detalle muestran primero **3.5 Botellas**
y debajo **3045 ml**. El costo sigue siendo **$65 por botella**. El aviso de stock bajo
aparece cuando queden **una botella o menos**, equivalente a **870 ml**. Estas
equivalencias no distinguen envases cerrados de abiertos.

Stock inicial y aviso mínimo siempre cuentan la presentación elegida. Para un tinte
de **90 g por tubo**, elige **Tubos**, escribe contenido **90**, unidad **g**, stock
**3.5** y aviso **1**. Quedan **3.5 Tubos / 315 g** y se avisa al llegar a un tubo o
menos (**90 g**).

En **Presentación** puedes elegir Botellas o Tubos, o escribir otra, por ejemplo
Frascos. En **Unidad del contenido** puedes elegir ml, l o g, o escribir una nueva.
La nueva opción queda disponible para otros productos después de guardar; preparar
una propuesta o dejar un formulario sin guardar no agrega opciones.

Las cantidades de contenido se conservan en la unidad elegida. Por ejemplo, una
botella de **0.870 l** con stock **3.5** corresponde a **3.045 l**. No se convierten
litros a ml de forma implícita ni se convierten gramos a mililitros. Los envases
abiertos pueden contarse con fracciones de presentación.

El conteo es opcional. Vacío deja el producto con cero existencias y el conteo
pendiente; escribir cero registra que lo contaste y no hay existencias.
Marca y descripción están en **Otros datos opcionales**. El aviso mínimo está junto
al stock y al precio, siempre expresado en presentaciones.

## Con el asistente

Puedes escribir:

> Registra peróxido de 30 volúmenes marca Kuul. Cada botella trae 870 ml, cuesta
> 65 pesos, tengo 3.5 botellas y quiero aviso cuando quede una botella.

El asistente abre la propuesta del producto. Revisa el nombre, contenido, costo,
presentación, cantidad, unidad y aviso mínimo. Para corregirlos, usa **Actualizar propuesta**; después pulsa
**Confirmar y guardar**. Enviar el mensaje prepara los datos; el guardado requiere
el botón de confirmación. Si falta el contenido para convertir botellas, el
formulario lo indica y conserva los datos para que puedas completarlo.

Si una propuesta ya no se puede abrir, la aplicación vuelve al asistente con un
aviso. Puedes abrir un registro pendiente de tu sesión o preparar otro.

## Existencias y finanzas

El conteo inicial crea un movimiento de **ajuste** en el historial del producto.
El producto y ese movimiento se guardan juntos. Reenviar el mismo formulario no
duplica el producto ni el conteo.

Contar lo que ya tienes conserva el saldo financiero y no crea un gasto. Registra
las compras nuevas por separado en **Gastos**. Después de crear el producto, usa
**Registrar movimiento** para entradas, consumos o nuevos conteos. Ese formulario
indica la unidad del contenido (ml, l, g u otra registrada): escribe la cantidad en
esa unidad. Editar el precio o el aviso mínimo no reinicia las existencias. Un
producto con movimientos conserva su presentación, contenido y unidad para no
alterar las equivalencias del historial.

## Actualización de la aplicación

La migración `inventario.0002_producto_clave_alta` identifica el alta para evitar
duplicados. La nueva `inventario.0003_presentacion_y_unidades_personalizadas` agrega
la presentación y las opciones iniciales Botellas, Tubos, ml, l, g y unidad. Conserva
las cantidades y los movimientos existentes, sin atribuir una presentación que
Marisol no haya indicado. En Railway se aplica con el paso previo de migraciones
del servicio web al publicar el código. La publicación requiere el OK de Walter.
