import uuid

from django import forms

from .constants import INITIAL_FIELDS, MAX_STOCK, QuantityMode, STOCK_DECIMAL_PLACES, STOCK_MAX_DIGITS, STOCK_QUANTUM, ZERO
from .messages import Error, Info, Label
from .models import MovimientoStock, Producto


def decorar(form):
    for field in form.fields.values():
        field.widget.attrs["class"] = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"


class ProductoForm(forms.ModelForm):
    cantidad_inicial = forms.DecimalField(
        required=False, max_digits=STOCK_MAX_DIGITS, decimal_places=STOCK_DECIMAL_PLACES,
        min_value=ZERO, label=Label.InitialQuantity, help_text=Info.QuantityHelp,
    )
    modo_cantidad = forms.ChoiceField(required=False, choices=QuantityMode.choices, initial=QuantityMode.BASE, label=Label.QuantityMode)
    clave_alta = forms.UUIDField(required=False, widget=forms.HiddenInput, initial=uuid.uuid4)

    class Meta:
        model = Producto
        fields = ["nombre", "marca", "descripcion", "unidad", "contenido_envase", "costo_envase", "stock_minimo", "activo"]
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 3})}
        labels = {"nombre": Label.Name, "unidad": Label.Unit, "contenido_envase": Label.Content, "costo_envase": Label.Cost}
        help_texts = {"unidad": Info.UnitHelp, "contenido_envase": Info.ContentHelp}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["unidad"].initial = Producto.Unidad.UNIDADES
        else:
            for name in INITIAL_FIELDS:
                self.fields.pop(name, None)
        decorar(self)

    def clean(self):
        datos = super().clean()
        cantidad = datos.get("cantidad_inicial")
        if self.instance.pk:
            return datos
        modo = datos.get("modo_cantidad") or QuantityMode.BASE
        datos["modo_cantidad"] = modo
        if cantidad is None:
            return datos
        unidad = datos.get("unidad")
        contenido = datos.get("contenido_envase")
        if not unidad or "contenido_envase" in self.errors or "modo_cantidad" in self.errors:
            return datos
        if modo == QuantityMode.ENVASES:
            if contenido is None:
                self.add_error("contenido_envase", Error.MissingContent)
                return datos
            cantidad *= contenido
        if cantidad > MAX_STOCK:
            self.add_error("cantidad_inicial", Error.StockTooLarge)
        elif cantidad != cantidad.quantize(STOCK_QUANTUM):
            self.add_error("cantidad_inicial", Error.StockPrecision)
        elif unidad == Producto.Unidad.UNIDADES and cantidad != cantidad.to_integral_value():
            self.add_error("cantidad_inicial", Error.FractionalPieces)
        elif not datos.get("activo"):
            self.add_error("activo", Error.InactiveProduct)
        else:
            datos["stock_inicial_calculado"] = cantidad
        return datos


class MovimientoForm(forms.Form):
    tipo = forms.ChoiceField(choices=MovimientoStock.Tipo.choices)
    cantidad = forms.DecimalField(max_digits=14, decimal_places=3, min_value=0, label="Cantidad (para ajuste, existencia final)")
    unidad = forms.ChoiceField(choices=Producto.Unidad.choices)
    motivo = forms.CharField(max_length=300)
    version = forms.IntegerField(widget=forms.HiddenInput)
    clave_operacion = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        decorar(self)

    def clean(self):
        datos = super().clean()
        if datos.get("tipo") != "ajuste" and datos.get("cantidad") == 0:
            self.add_error("cantidad", "La entrada o salida debe ser mayor que cero.")
        return datos
