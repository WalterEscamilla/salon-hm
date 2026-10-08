import uuid
from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.inventario.forms import decorar
from .models import Gasto


class FechaPasadaForm(forms.Form):
    def validar_fecha(self, campo):
        fecha = self.cleaned_data[campo]
        if fecha > timezone.localdate():
            raise forms.ValidationError("Elige hoy o una fecha anterior; aquí registramos dinero que ya se movió.")
        return fecha

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        decorar(self)


class GastoForm(FechaPasadaForm):
    fecha = forms.DateField(initial=timezone.localdate, label="Fecha del pago", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    concepto = forms.CharField(max_length=200, label="¿En qué se gastó?", widget=forms.TextInput(attrs={"placeholder": "Luz de esta semana, lámpara nueva…"}))
    categoria = forms.ChoiceField(choices=Gasto.Categoria.choices, label="Tipo de gasto")
    importe = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), label="Importe pagado (MXN)")
    notas = forms.CharField(max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Notas (opcional)")
    clave_operacion = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput)
    version = forms.IntegerField(initial=1, min_value=1, widget=forms.HiddenInput)

    def clean_fecha(self):
        return self.validar_fecha("fecha")


class BaseFinancieraForm(FechaPasadaForm):
    saldo_inicial = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, label="Dinero disponible al comenzar (MXN)")
    fecha_inicio = forms.DateField(label="Contar movimientos desde", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), help_text="Se suman visitas y gastos desde este día, inclusive. No vuelvas a incluir en el saldo inicial los movimientos de ese período.")
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def clean_fecha_inicio(self):
        return self.validar_fecha("fecha_inicio")


class AnularGastoForm(forms.Form):
    motivo = forms.CharField(max_length=300, label="Motivo de la anulación")
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        decorar(self)
