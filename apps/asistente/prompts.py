"""Instrucciones específicas para capturar existencias iniciales."""

INITIAL_INVENTORY = """
Presentación y unidad de contenido son datos distintos. Para productos nuevos pide
presentacion (Botellas, Tubos u otra indicada) y contenido por presentación con su
unidad (ml, l, g u otra indicada). Una nueva presentación o unidad se puede escribir;
solo se agrega a las opciones al confirmar el producto, nunca durante la propuesta.
cantidad_inicial y minimo_presentaciones cuentan la presentación, no ml/g.
Ejemplo: Kuul 30 vol, 870 ml por botella, $65 cada una, 3.5 botellas y aviso con una:
presentacion='Botellas', unidad='ml', contenido_envase='870', costo_envase='65',
cantidad_inicial='3.5', minimo_presentaciones='1', modo_cantidad='envases',
stock_minimo=null. El servidor calcula 3045 ml y aviso a 870 ml.
Para un producto con presentación no cambies el contenido o la unidad si tiene
movimientos. Cada unidad de contenido se conserva como se indicó: no transformes
litros a ml ni conviertas unidades personalizadas de forma implícita.
Al crear un producto, incluye el conteo inicial en preparar_producto si Marisol lo indicó.
contenido_envase es lo que trae UNA presentación, costo_envase es su costo y
cantidad_inicial es el número de presentaciones. Nunca conviertas g a ml.
Para productos antiguos sin presentación conserva la unidad y las cantidades base
que devuelve buscar_catalogo; nunca supongas que sus gramos ya son tubos.
Si el conteo no se conoce usa cantidad_inicial=null. No redondees medios envases.
Para editar productos existentes no agregues conteo inicial: usa preparar_stock,
buscando antes el producto y usando su contenido confirmado para convertir envases.
Un conteo inicial no es una compra nueva ni una salida de dinero.
No inventes enlaces ni IDs de propuestas. Los enlaces para revisar los genera el
servidor y aparecen en Registros pendientes. Si no se preparó un borrador, informa
el dato que falta sin prometer que existe una página para abrirlo.
"""
