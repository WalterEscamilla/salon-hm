"""Textos del inventario, separados de las reglas y operaciones."""


class Error:
    MissingContent = "Indica cuánto trae cada botella o envase para calcular las existencias."
    FractionalPieces = "Las piezas se cuentan completas. Para una botella abierta, elige ml o g e indica su contenido."
    StockPrecision = "El total debe poder expresarse con hasta tres decimales. Revisa el contenido y la cantidad."
    StockTooLarge = "La cantidad total supera el límite del inventario. Revisa el conteo."
    InitialStockOnEdit = "El conteo inicial se registra al crear el producto. Usa Registrar movimiento para cambiar existencias."
    OperationConflict = "Esta operación ya se utilizó con otros datos. Recarga el formulario."
    InactiveProduct = "Activa el producto antes de registrar existencias."


class Label:
    InitialQuantity = "Existencias iniciales (si las conoces)"
    QuantityMode = "Esta cantidad está expresada en"
    BaseQuantity = "ml, g o piezas"
    ContainersQuantity = "Botellas o envases"
    Name = "Nombre del producto"
    Unit = "Unidad para llevar el inventario"
    Content = "Contenido por botella o envase (en ml, g o piezas)"
    Cost = "Costo por botella o envase (MXN)"
    NewProduct = "Nuevo producto"
    EditProduct = "Editar producto"
    ManualInventory = "INVENTARIO MANUAL"
    OptionalData = "Otros datos opcionales"
    SaveProduct = "Guardar producto"
    Back = "Volver"
    InitialStock = "Conteo inicial"
    InitialStockReason = "Conteo de existencias iniciales; no representa una compra nueva."


class Info:
    Introduction = "Registra el producto y, si lo sabes, cuántos tienes en este mismo formulario."
    UnitHelp = "Para líquidos elige ml y para productos medidos en gramos elige g. Usa piezas para objetos completos."
    QuantityHelp = "Puedes escribir 3.5 si tienes tres botellas y media. Selecciona Botellas o envases e indica cuánto trae cada uno. Vacío deja el conteo pendiente."
    ContentHelp = "Ejemplo: 875 si cada botella trae 875 ml y elegiste ml como unidad."
    InitialStockHelp = "Este conteo conserva el saldo financiero. Las compras nuevas se registran por separado en Gastos."
    EditingStock = "Las existencias se modifican con Registrar movimiento desde el detalle del producto."
    PendingCount = "Guardamos el producto. Puedes registrar las existencias desde Registrar movimiento."
    SavedWithStock = "Guardamos el producto y sus existencias iniciales."
    ProductSaved = "Guardamos los datos del producto."
    ContainersRemaining = "Botellas o envases equivalentes"
