"""URL utama. Setiap layar baru didaftarkan di sini saat app-nya diisi."""

from django.urls import include, path

from core import views as core_views
from ledger import views as ledger_views
from onboarding import views as onboarding_views
from reports import views as reports_views

urlpatterns = [
    path("healthz", core_views.healthz, name="healthz"),
    path("masuk", core_views.LoginView.as_view(), name="login"),
    path("keluar", core_views.logout_view, name="logout"),
    path("pengaturan/akun", core_views.account_settings, name="account_settings"),
    path("pengaturan/profil", core_views.profile_view, name="profile"),
    path(
        "pengaturan/saldo-awal",
        ledger_views.opening_balance,
        name="opening_balance",
    ),
    path(
        "pengaturan/saldo-awal/koreksi",
        ledger_views.opening_correction,
        name="opening_correction",
    ),
    path("pengaturan/", include("master.urls")),
    path("stok/", include("stock.urls")),
    path("rekap/", include("reports.urls")),
    path("transaksi/", include("ledger.urls")),
    path("setup", onboarding_views.setup_entry, name="setup"),
    path("setup/akun", onboarding_views.step_account, name="setup_account"),
    path("setup/profil", onboarding_views.step_profile, name="setup_profile"),
    path("setup/saldo", onboarding_views.step_balance, name="setup_balance"),
    path("setup/stok", onboarding_views.step_stock, name="setup_stock"),
    path("setup/ringkasan", onboarding_views.step_review, name="setup_review"),
    path("", reports_views.dashboard, name="dashboard"),
]

# Halaman error ramah (Bahasa Indonesia) saat DEBUG=False.
handler403 = "core.views.error_403"
handler404 = "core.views.error_404"
handler500 = "core.views.error_500"
