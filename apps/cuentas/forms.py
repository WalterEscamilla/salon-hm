from django.contrib.auth.forms import AuthenticationForm


class AccesoForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "Revisa tu usuario y contraseña e inténtalo de nuevo.",
        "inactive": "Esta cuenta no tiene acceso. Contacta a la administradora.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Usuario"
        self.fields["username"].widget.attrs.update(
            {"class": "form-control form-control-lg", "autocomplete": "username", "autocapitalize": "none", "spellcheck": "false"}
        )
        self.fields["password"].label = "Contraseña"
        self.fields["password"].widget.attrs.update(
            {"class": "form-control form-control-lg", "autocomplete": "current-password"}
        )

