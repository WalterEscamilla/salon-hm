from django import forms

from .models import Cliente


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nombre", "telefono", "notas"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "autocomplete": "name"}),
            "telefono": forms.TextInput(attrs={"class": "form-control", "type": "tel", "autocomplete": "tel"}),
            "notas": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

