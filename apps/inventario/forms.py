import uuid

from django import forms

from .models import MovimientoStock, Producto


def decorar(form):
    for field in form.fields.values():
        field.widget.attrs["class"] = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"


class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = ["nombre", "marca", "descripcion", "unidad", "contenido_envase", "costo_envase", "stock_minimo", "activo"]
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["unidad"].initial = Producto.Unidad.UNIDADES
        decorar(self)


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
