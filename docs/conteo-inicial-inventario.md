# Registrar los productos que ya tienes

Entra a **Productos → Nuevo producto**. Para el ejemplo de Marisol, completa:

| Campo | Valor |
| --- | --- |
| Nombre | Peróxido 30 vol |
| Unidad para llevar el inventario | ml |
| Contenido por botella o envase | 875 |
| Costo por botella o envase (MXN) | 65 |
| Existencias iniciales | 3.5 |
| Esta cantidad está expresada en | Botellas o envases |

Pulsa **Guardar producto**. Quedan **3062.5 ml**, equivalentes a **3.5 botellas** de
875 ml. El costo sigue siendo **$65 por botella**. Las botellas equivalentes expresan
el volumen total: no distinguen envases cerrados de abiertos.

Si ya conoces el total en ml, gramos o piezas, escribe ese total y elige
**ml, g o piezas**. Para líquidos usa ml; para productos medidos en gramos usa g.
Las piezas deben ser enteras. Una botella abierta se puede contar con una fracción
de envase cuando se conoce su contenido. No se convierten gramos a mililitros.

El conteo es opcional. Vacío deja el producto con cero existencias y el conteo
pendiente; escribir cero registra que lo contaste y no hay existencias.
Marca, descripción y aviso de stock mínimo están en **Otros datos opcionales**.

## Con el asistente

Puedes escribir:

> Registra peróxido de 30 volúmenes. Cada botella trae 875 ml, cuesta 65 pesos y
> tengo 3.5 botellas.

El asistente abre la propuesta del producto. Revisa el nombre, contenido, costo,
cantidad y unidad. Para corregirlos, usa **Actualizar propuesta**; después pulsa
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
**Registrar movimiento** para entradas, consumos o nuevos conteos. Editar sus datos
no reinicia las existencias.

## Actualización de la aplicación

Esta actualización incluye la migración `inventario.0002_producto_clave_alta`,
que añade la identificación del alta para evitar duplicados. Conserva los productos
y movimientos existentes. En Railway se aplica con el paso previo de migraciones
del servicio web al publicar el código. La publicación requiere el OK de Walter.
