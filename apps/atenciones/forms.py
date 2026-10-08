import uuid

from django import forms
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.inventario.forms import decorar


class AtencionForm(forms.Form):
    nombre_cliente = forms.CharField(max_length=160, label="Nombre de la clienta")
    telefono = forms.CharField(max_length=30, required=False, label="Teléfono (si lo tienes)", widget=forms.TextInput(attrs={"type": "tel"}))
    cliente_id = forms.ModelChoiceField(queryset=Cliente.objects.none(), required=False, label="Elegir una clienta registrada (opcional)", empty_label="Buscar por nombre y teléfono")
    crear_nueva = forms.BooleanField(required=False, label="Es otra persona: crear una clienta nueva")
    fecha = forms.DateField(initial=timezone.localdate, label="Fecha del servicio", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    servicio = forms.CharField(max_length=2000, label="Servicio realizado", widget=forms.Textarea(attrs={"rows": 2}))
    precio_cobrado = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, label="Precio cobrado por esta visita (MXN)", help_text="Puedes dejarlo vacío si no lo recuerdas. Admite precios preferenciales y descuentos.")
    materiales = forms.CharField(max_length=4000, required=False, label="Materiales, tonos o fórmula utilizados", widget=forms.Textarea(attrs={"rows": 3}), help_text="Escribe lo que recuerdes; las cantidades son opcionales.")
    notas = forms.CharField(max_length=2000, required=False, label="Notas para la próxima visita", widget=forms.Textarea(attrs={"rows": 2}))
    clave_operacion = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput)
    version = forms.IntegerField(initial=1, min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente_id"].queryset = Cliente.objects.filter(archivado_en__isnull=True)
        decorar(self)

    def clean_fecha(self):
        fecha = self.cleaned_data["fecha"]
        if fecha > timezone.localdate():
            raise forms.ValidationError("Registra aquí un servicio ya realizado. Para una cita futura utiliza Agenda.")
        return fecha

    def clean(self):
        datos = super().clean()
        if datos.get("cliente_id") and datos.get("crear_nueva"):
            self.add_error("crear_nueva", "Elige una clienta existente o crea una nueva.")
        return datos


class AtencionPropuestaForm(AtencionForm):
    """Permite datos pendientes exclusivamente al preparar el formulario de IA."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ("nombre_cliente", "servicio", "fecha"):
            self.fields[campo].required = False

    def clean_fecha(self):
        if self.cleaned_data["fecha"] is None:
            return None
        return super().clean_fecha()


class DescripcionServicioForm(forms.Form):
    texto_asistente = forms.CharField(max_length=4000, required=False, label="Cuéntame qué hiciste", widget=forms.Textarea(attrs={"rows": 3, "class": "form-control", "placeholder": "Le hice retoque de raíz y corte, cobré 420 pesos y usé tinte 6.0 con peróxido de 20 volúmenes. Para la próxima vez, conservar el largo."}))

    def clean_texto_asistente(self):
        texto = self.cleaned_data["texto_asistente"]
        if not texto:
            raise forms.ValidationError("Describe el servicio para completar el formulario con IA.")
        return texto
