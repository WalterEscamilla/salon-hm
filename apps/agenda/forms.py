import uuid

from django import forms
from django.db.models import Q

from apps.catalogos.models import Servicio
from apps.clientes.models import Cliente

from .models import Cita


class CitaForm(forms.Form):
    cliente = forms.ModelChoiceField(label="Clienta", queryset=Cliente.objects.none(), empty_label="Selecciona una clienta")
    servicios = forms.ModelMultipleChoiceField(label="Servicios del catálogo", queryset=Servicio.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)
    motivo = forms.CharField(label="Servicio previsto", max_length=240, required=False, help_text="Escribe el servicio si todavía no lo tienes en el catálogo.")
    inicio = forms.DateTimeField(label="Inicio", input_formats=["%Y-%m-%dT%H:%M"], widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}))
    fin = forms.DateTimeField(label="Fin", input_formats=["%Y-%m-%dT%H:%M"], widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}))
    notas = forms.CharField(label="Notas privadas", max_length=3000, required=False, widget=forms.Textarea(attrs={"rows": 3}), help_text="Estas notas no se enviarán a Google Calendar.")
    estado = forms.ChoiceField(choices=Cita.Estado.choices)
    aceptar_traslape = forms.BooleanField(label="Acepto agendar en este horario aunque haya otra ocupación", required=False)
    confirmacion_traslape = forms.CharField(required=False, widget=forms.HiddenInput)
    clave_operacion = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput)
    version = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, cita=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente"].queryset = Cliente.objects.filter(archivado_en__isnull=True)
        if cita and cita.cliente.archivado_en:
            self.fields["cliente"].queryset = Cliente.objects.filter(Q(archivado_en__isnull=True) | Q(pk=cita.cliente_id))
        self.fields["servicios"].queryset = Servicio.objects.filter(activo=True)
        if cita:
            self.fields["servicios"].queryset = Servicio.objects.filter(Q(activo=True) | Q(servicioprevisto__cita=cita)).distinct()
        for nombre, field in self.fields.items():
            if isinstance(field.widget, (forms.HiddenInput, forms.CheckboxSelectMultiple)):
                continue
            field.widget.attrs["class"] = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-select" if isinstance(field.widget, forms.Select) else "form-control"

    def clean(self):
        data = super().clean()
        if data.get("fin") and data.get("inicio") and data["fin"] <= data["inicio"]:
            self.add_error("fin", "El fin debe ser posterior al inicio.")
        if not data.get("motivo") and not data.get("servicios"):
            self.add_error("motivo", "Indica el servicio previsto o elige uno del catálogo.")
        return data
