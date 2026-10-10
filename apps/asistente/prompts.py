"""Instrucciones específicas para capturar existencias iniciales."""

INITIAL_INVENTORY = """
Al crear un producto, incluye el conteo inicial en preparar_producto si Marisol lo indicó.
Para líquidos en botellas, unidad=ml, contenido_envase es lo que trae UNA botella,
costo_envase es el costo de UNA botella, cantidad_inicial es el número de botellas
y modo_cantidad=envases. Para productos pesados usa g. Para piezas completas usa
unidad y modo_cantidad=base. Nunca conviertas gramos a mililitros.
Ejemplo: peróxido 30 vol, botella de 875 ml, costo 65 pesos, tres botellas y media:
unidad=ml, contenido_envase="875", costo_envase="65", cantidad_inicial="3.5",
modo_cantidad=envases. El servidor calculará el contenido total. No redondees medios envases.
Si el conteo no se conoce usa cantidad_inicial=null, modo_cantidad=null.
Para editar productos existentes no agregues conteo inicial: usa preparar_stock,
buscando antes el producto y usando su contenido confirmado para convertir envases.
Un conteo inicial no es una compra nueva ni una salida de dinero.
No inventes enlaces ni IDs de propuestas. Los enlaces para revisar los genera el
servidor y aparecen en Registros pendientes. Si no se preparó un borrador, informa
el dato que falta sin prometer que existe una página para abrirlo.
"""
