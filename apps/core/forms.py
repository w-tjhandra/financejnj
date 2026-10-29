"""Form autentikasi dan pengaturan akun. Pesan memakai Bahasa Indonesia."""

from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.core.exceptions import ValidationError

from core import messages as core_messages


class CompanyProfileForm(forms.Form):
    """Identitas usaha (S-20). Logo fase 2, jadi belum ditampilkan."""

    name = forms.CharField(
        max_length=100,
        label="Nama usaha",
        error_messages={"required": core_messages.BUSINESS_NAME_REQUIRED},
        widget=forms.TextInput(attrs={"class": "input", "autofocus": True}),
    )
    address = forms.CharField(
        max_length=300,
        required=False,
        label="Alamat",
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "street-address"}),
    )
    phone = forms.CharField(
        max_length=30,
        required=False,
        label="Telepon",
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "tel"}),
    )
    email = forms.EmailField(
        max_length=254,
        required=False,
        label="Email",
        error_messages={"invalid": core_messages.EMAIL_INVALID},
        widget=forms.EmailInput(attrs={"class": "input", "autocomplete": "email"}),
    )

    def clean_name(self) -> str:
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise ValidationError(core_messages.BUSINESS_NAME_REQUIRED)
        return name

    def clean_address(self) -> str:
        return (self.cleaned_data.get("address") or "").strip()

    def clean_phone(self) -> str:
        return (self.cleaned_data.get("phone") or "").strip()

    def clean_email(self) -> str:
        return (self.cleaned_data.get("email") or "").strip()


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
