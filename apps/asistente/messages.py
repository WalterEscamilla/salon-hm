"""Mensajes de recuperación y de preparación de inventario."""


class Error:
    ProposalUnavailable = "No pudimos abrir esa propuesta. Puede pertenecer a una sesión anterior. Abre un registro pendiente o prepara uno nuevo desde el asistente."
    InitialStockOnEdit = "El conteo inicial solo se agrega al crear un producto. Para un producto existente, prepara un movimiento de stock."


class Info:
    InitialStockTool = "Prepara un producto y sus existencias sin guardar. presentacion indica Botellas, Tubos u otro envase; unidad es la unidad de su contenido (ml, l, g u otra indicada). contenido_envase y costo_envase corresponden a una presentación. cantidad_inicial y minimo_presentaciones cuentan presentaciones: 3.5 botellas y aviso de 1 botella son '3.5' y '1'. Con presentación, modo_cantidad='envases' y stock_minimo=null. Solo productos antiguos sin presentación usan stock_minimo en la unidad del contenido y modo_cantidad='base'. Al editar, cantidad_inicial y modo_cantidad deben ser null; campos null conservan sus valores. No inventes cantidades. Marisol confirma en la página."
