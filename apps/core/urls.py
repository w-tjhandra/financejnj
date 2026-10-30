"""URL Core: health, auth, profile, period lock."""

from django.urls import path

from core import views

# No app_name - URLs are included at root level without namespace
urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
    path("masuk", views.LoginView.as_view(), name="login"),
    path("keluar", views.logout_view, name="logout"),
    path("pengaturan/akun", views.account_settings, name="account_settings"),
    path("pengaturan/profil", views.profile_view, name="profile"),
    path("pengaturan/kunci-periode", views.period_lock_list, name="period_lock_list"),
    path(
        "pengaturan/kunci-periode/<str:period>", views.period_lock_action, name="period_lock_action"
    ),
]
