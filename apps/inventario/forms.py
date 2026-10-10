import uuid

from django import forms
from django.core.exceptions import ValidationError

from .constants import (DEFAULT_CONTENT_UNITS, DEFAULT_PRESENTATIONS, INITIAL_FIELDS,
    MAX_STOCK, NEW_OPTION, OptionType, PRESENTATION_FIELDS, PRESENTATION_MAX_LENGTH,
    QuantityMode, STOCK_DECIMAL_PLACES, STOCK_MAX_DIGITS, STOCK_QUANTUM, UNIT_MAX_LENGTH, ZERO)
from .messages import Error, Info, Label
from .models import MovimientoStock, OpcionInventario, Producto
from .quantities import CantidadPresentacionesField, contenido_exacto
from .widgets import FraccionPresentacionWidget, OpcionAmpliableWidget


def decorar(form):
    for field in form.fields.values():
        field.widget.attrs["class"] = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"


class ProductoForm(forms.ModelForm):
    unidad = forms.CharField(max_length=UNIT_MAX_LENGTH, label=Label.ContentUnit)
    minimo_presentaciones = forms.DecimalField(required=False, max_digits=STOCK_MAX_DIGITS,
        decimal_places=STOCK_DECIMAL_PLACES, min_value=ZERO, label=Label.PresentationMinimum,
        help_text=Info.PresentationMinimumHelp)
    cantidad_inicial = CantidadPresentacionesField(required=False,
        label=Label.InitialQuantity, help_text=Info.QuantityHelp)
    corregir_presentacion = forms.BooleanField(required=False, label=Label.CorrectPresentation,
        help_text=Info.PresentationCorrection)
    modo_cantidad = forms.ChoiceField(required=False, choices=QuantityMode.choices, initial=QuantityMode.BASE, label=Label.QuantityMode)
    clave_alta = forms.UUIDField(required=False, widget=forms.HiddenInput, initial=uuid.uuid4)

    class Meta:
        model = Producto
        fields = ["nombre", "presentacion", "marca", "descripcion", "unidad", "contenido_envase", "costo_envase", "stock_minimo", "activo"]
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 3})}
        labels = {"nombre": Label.Name, "unidad": Label.Unit, "contenido_envase": Label.Content, "costo_envase": Label.Cost}
        help_texts = {"unidad": Info.UnitHelp, "contenido_envase": Info.ContentHelp}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["unidad"].initial = Producto.Unidad.UNIDADES
            self.fields.pop("corregir_presentacion")
        else:
            for name in INITIAL_FIELDS:
                self.fields.pop(name, None)
            self.fields["minimo_presentaciones"].initial = self.instance.minimo_presentaciones if self.instance.presentacion else None
        presentation = (self.data.get("presentacion") if self.is_bound else self.initial.get("presentacion")) or ""
        if presentation:
            self.fields["stock_minimo"].required = False
            self.fields["stock_minimo"].widget = forms.HiddenInput()
            if "modo_cantidad" in self.fields:
                self.fields["modo_cantidad"].widget = forms.HiddenInput()
                self.fields["modo_cantidad"].initial = QuantityMode.ENVASES
            if "cantidad_inicial" in self.fields:
                self.fields["cantidad_inicial"].label = Label.PresentationStock
            self.fields["contenido_envase"].label = Label.PresentationContent
            self.fields["costo_envase"].label = Label.PresentationPrice
        decorar(self)

    def clean(self):
        datos = super().clean()
        presentacion = datos.get("presentacion")
        contenido = datos.get("contenido_envase")
        if presentacion:
            datos["modo_cantidad"] = QuantityMode.ENVASES
            if contenido is None and "contenido_envase" not in self.errors:
                self.add_error("contenido_envase", Error.PresentationContent)
            minimo = datos.get("minimo_presentaciones")
            if minimo is None and self.instance.pk:
                minimo = self.instance.minimo_presentaciones
            minimo = minimo if minimo is not None else ZERO
            datos["minimo_presentaciones"] = minimo
            if contenido is not None:
                total_minimo = minimo * contenido
                if total_minimo > MAX_STOCK:
                    self.add_error("minimo_presentaciones", Error.MinimumTooLarge)
                elif total_minimo != total_minimo.quantize(STOCK_QUANTUM):
                    self.add_error("minimo_presentaciones", Error.MinimumPrecision)
                else:
                    datos["stock_minimo"] = total_minimo.quantize(STOCK_QUANTUM)
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
        else:
            contenido = 1
        try:
            cantidad = contenido_exacto(cantidad, contenido)
        except ValidationError as error:
            self.add_error("cantidad_inicial", error)
            return datos
        if unidad == Producto.Unidad.UNIDADES and cantidad != cantidad.to_integral_value():
            self.add_error("cantidad_inicial", Error.FractionalPieces)
        elif not datos.get("activo"):
            self.add_error("activo", Error.InactiveProduct)
        else:
            datos["stock_inicial_calculado"] = cantidad.quantize(STOCK_QUANTUM)
        return datos


class ProductoPresentacionForm(ProductoForm):
    """Formulario de captura: cantidades siempre en la presentación elegida."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["presentacion"].required = True
        self.fields["presentacion"].label = Label.Presentation
        self.fields["presentacion"].help_text = Info.PresentationHelp
        self.fields["unidad"].initial = None
        self.fields["unidad"].help_text = Info.ContentUnitHelp
        self.configurar_opcion("presentacion", OptionType.PRESENTATION, DEFAULT_PRESENTATIONS, PRESENTATION_MAX_LENGTH)
        self.configurar_opcion("unidad", OptionType.UNIT, DEFAULT_CONTENT_UNITS, UNIT_MAX_LENGTH)
        self.fields["contenido_envase"].required = True
        self.fields["contenido_envase"].error_messages["required"] = Error.PresentationContent
        self.fields["contenido_envase"].label = Label.PresentationContent
        self.fields["contenido_envase"].help_text = Info.PresentationContentHelp
        self.fields["costo_envase"].label = Label.PresentationPrice
        self.fields["costo_envase"].help_text = Info.PresentationPriceHelp
        self.fields["stock_minimo"].required = False
        self.fields["stock_minimo"].widget = forms.HiddenInput()
        if "cantidad_inicial" in self.fields:
            self.fields["cantidad_inicial"].label = Label.PresentationStock
            self.fields["cantidad_inicial"].help_text = Info.PresentationQuantityHelp
            self.fields["cantidad_inicial"].widget = FraccionPresentacionWidget(attrs={"class": "form-control"})
            self.fields["modo_cantidad"].initial = QuantityMode.ENVASES
            self.fields["modo_cantidad"].widget = forms.HiddenInput()
        if self.instance.pk:
            if not self.instance.puede_corregir_presentacion:
                self.fields.pop("corregir_presentacion", None)
                if self.instance.movimientos.exists():
                    for name in ("presentacion", "unidad", "contenido_envase"):
                        self.fields[name].disabled = True
                        self.fields[name].help_text = Info.PresentationLocked
        self.order_fields(PRESENTATION_FIELDS)

    def configurar_opcion(self, campo, tipo, defaults, max_length):
        widget = OpcionAmpliableWidget(attrs={"class": "form-select", "data_maxlength": max_length})
        self.fields[campo].widget = widget
        valor = widget.value_from_datadict(self.data, self.files, campo) if self.is_bound else self.initial.get(campo, self.fields[campo].initial)
        actual = str(valor or "").strip()
        opciones = list(defaults) + list(OpcionInventario.objects.filter(tipo=tipo).values_list("nombre", flat=True))
        if actual and actual != NEW_OPTION:
            opciones.append(actual)
        valores = dict.fromkeys(opciones)
        widget.choices = [("", Label.ChooseOption), *((valor, valor) for valor in valores), (NEW_OPTION, Label.NewOption)]

    def clean_presentacion(self):
        return self.validar_opcion("presentacion")

    def clean_unidad(self):
        return self.validar_opcion("unidad")

    def validar_opcion(self, campo):
        valor = self.cleaned_data[campo]
        if valor == NEW_OPTION:
            raise ValidationError(Error.InvalidNewOption)
        return valor

    @property
    def campos_principales(self):
        return [self[name] for name in PRESENTATION_FIELDS if name in self.fields]

    @property
    def campos_opcionales(self):
        return [self[name] for name in self.fields if name not in PRESENTATION_FIELDS and not self.fields[name].widget.is_hidden]


class MovimientoForm(forms.Form):
    tipo = forms.ChoiceField(choices=MovimientoStock.Tipo.choices)
    cantidad = forms.DecimalField(max_digits=14, decimal_places=3, min_value=0, label="Cantidad (para ajuste, existencia final)")
    unidad = forms.CharField(max_length=UNIT_MAX_LENGTH, widget=forms.Select())
    motivo = forms.CharField(max_length=300)
    version = forms.IntegerField(widget=forms.HiddenInput)
    clave_operacion = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        unidades = dict(Producto.Unidad.choices)
        unidades.update({unidad: unidad for unidad in Producto.objects.order_by("unidad").values_list("unidad", flat=True).distinct()})
        self.fields["unidad"].widget.choices = sorted(unidades.items())
        decorar(self)

    def clean(self):
        datos = super().clean()
        if datos.get("tipo") != "ajuste" and datos.get("cantidad") == 0:
            self.add_error("cantidad", "La entrada o salida debe ser mayor que cero.")
        return datos
