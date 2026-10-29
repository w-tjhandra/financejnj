"""Form autentikasi. Pesan gagal selalu generik (FR-01)."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "Username atau kata sandi salah.",
        "inactive": "Akun ini tidak aktif.",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {
                "class": "input",
                "autocomplete": "username",
                "autofocus": True,
                "required": True,
                "aria-describedby": "id_username_help",
            }
        )
        self.fields["password"].widget.attrs.update(
            {
                "class": "input",
                "autocomplete": "current-password",
                "required": True,
            }
        )
