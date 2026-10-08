from django import forms

from .models import ConfiguracionSalon


class ConfiguracionForm(forms.ModelForm):
    class Meta:
        model = ConfiguracionSalon
        fields = ["nombre", "zona_horaria"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control form-control-lg"}),
            "zona_horaria": forms.TextInput(attrs={"class": "form-control form-control-lg", "list": "zonas-horarias", "spellcheck": "false"}),
        }
        help_texts = {"zona_horaria": "Las fechas se mostrarán en esta zona. Los registros se almacenan en UTC."}

