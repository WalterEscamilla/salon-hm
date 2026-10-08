import uuid

from django import forms
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.inventario.forms import decorar


class AtencionForm(forms.Form):
    permitir_costos_pendientes = False
    nombre_cliente = forms.CharField(max_length=160, label="Nombre de la clienta")
    telefono = forms.CharField(max_length=30, required=False, label="Teléfono (si lo tienes)", widget=forms.TextInput(attrs={"type": "tel"}))
    cliente_id = forms.ModelChoiceField(queryset=Cliente.objects.none(), required=False, label="Elegir una clienta registrada (opcional)", empty_label="Buscar por nombre y teléfono")
    crear_nueva = forms.BooleanField(required=False, label="Es otra persona: crear una clienta nueva")
    fecha = forms.DateField(initial=timezone.localdate, label="Fecha del servicio", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    servicio = forms.CharField(max_length=2000, label="Servicio realizado", widget=forms.Textarea(attrs={"rows": 2}))
    precio_cobrado = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, label="Precio cobrado por esta visita (MXN)", help_text="Puedes dejarlo vacío si no lo recuerdas. Admite precios preferenciales y descuentos.")
    costo_materiales = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, label="Costo de materiales utilizados (MXN)", help_text="Lo que costaron los materiales que usaste, aunque los compraras antes. Vacío significa desconocido; escribe 0 si no hubo costo.")
    otros_gastos = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, label="Otros gastos de esta visita (MXN)", help_text="Por ejemplo, un gasto adicional de este servicio. Escribe 0 si no hubo otros gastos. Los pagos generales de luz se registran en Finanzas.")
    gastos_pagados_en_visita = forms.BooleanField(required=False, label="Estos gastos se pagaron ahora y no están registrados en Gastos", help_text="Marca solo si ambos importes salieron del dinero del salón en esta visita. Se descontarán del saldo. Si usaste materiales comprados antes o ya registraste el pago en Finanzas, deja sin marcar.")
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
        if datos.get("gastos_pagados_en_visita") and not self.permitir_costos_pendientes:
            for campo in ("costo_materiales", "otros_gastos"):
                if datos.get(campo) is None:
                    self.add_error(campo, "Indica el importe pagado; usa 0 si no hubo gasto en este concepto.")
        return datos


class AtencionPropuestaForm(AtencionForm):
    """Permite datos pendientes exclusivamente al preparar el formulario de IA."""
    permitir_costos_pendientes = True
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ("nombre_cliente", "servicio", "fecha"):
            self.fields[campo].required = False

    def clean_fecha(self):
        if self.cleaned_data["fecha"] is None:
            return None
        return super().clean_fecha()


class DescripcionServicioForm(forms.Form):
    texto_asistente = forms.CharField(max_length=4000, required=False, label="Cuéntame qué hiciste", widget=forms.Textarea(attrs={"rows": 3, "class": "form-control", "placeholder": "Le hice retoque de raíz y corte. Cobré 500 pesos, usé tinte 6.0 y peróxido: los materiales costaron 80 y hubo otros gastos de 20. Para la próxima vez, conservar el largo."}))

    def clean_texto_asistente(self):
        texto = self.cleaned_data["texto_asistente"]
        if not texto:
            raise forms.ValidationError("Describe el servicio para completar el formulario con IA.")
        return texto
