"""Form autentikasi dan pengaturan akun. Pesan memakai Bahasa Indonesia."""

from __future__ import annotations

from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.core.exceptions import ValidationError

from core import messages as core_messages


class LoginForm(AuthenticationForm):
    """Pesan gagal selalu generik agar keberadaan username tidak bocor."""

    error_messages = {
        "invalid_login": "Username atau kata sandi salah.",
        # Jangan bedakan akun nonaktif dari kredensial salah.
        "inactive": "Username atau kata sandi salah.",
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


class AccountPasswordChangeForm(PasswordChangeForm):
    """Ganti kata sandi: wajib sandi lama, minimal 10 karakter, ≠ username."""

    error_messages = {
        **PasswordChangeForm.error_messages,
        "password_incorrect": core_messages.OLD_PASSWORD_INCORRECT,
        "password_mismatch": core_messages.PASSWORD_MISMATCH,
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "Kata sandi lama"
        self.fields["old_password"].widget.attrs.update(
            {"class": "input", "autocomplete": "current-password", "autofocus": True}
        )
        self.fields["new_password1"].label = "Kata sandi baru"
        self.fields[
            "new_password1"
        ].help_text = "Minimal 10 karakter dan tidak boleh sama dengan nama pengguna."
        self.fields["new_password1"].widget.attrs.update(
            {"class": "input", "autocomplete": "new-password"}
        )
        self.fields["new_password2"].label = "Konfirmasi kata sandi baru"
        self.fields["new_password2"].help_text = "Ulangi kata sandi baru."
        self.fields["new_password2"].widget.attrs.update(
            {"class": "input", "autocomplete": "new-password"}
        )

    def clean_new_password1(self) -> str:
        password = self.cleaned_data.get("new_password1") or ""
        if password and self.user is not None:
            if password.casefold() == self.user.username.casefold():
                raise ValidationError(core_messages.PASSWORD_SAME_AS_USERNAME)
        return password
