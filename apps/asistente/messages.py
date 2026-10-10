"""Mensajes de recuperación y de preparación de inventario."""


class Error:
    ProposalUnavailable = "No pudimos abrir esa propuesta. Puede pertenecer a una sesión anterior. Abre un registro pendiente o prepara uno nuevo desde el asistente."
    InitialStockOnEdit = "El conteo inicial solo se agrega al crear un producto. Para un producto existente, prepara un movimiento de stock."


class Info:
    InitialStockTool = "Prepara un producto nuevo con sus existencias iniciales en una sola propuesta. No guarda: Marisol confirma en la página. Usa cantidad_inicial=null si no conoce el conteo; modo_cantidad='envases' para botellas o 'base' para ml/g/piezas. Al editar, cantidad_inicial y modo_cantidad deben ser null."
