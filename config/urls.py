"""URL utama. Setiap layar baru didaftarkan di sini saat app-nya diisi."""

from django.urls import path

from core import views as core_views
from reports import views as reports_views

urlpatterns = [
    path("healthz", core_views.healthz, name="healthz"),
    path("masuk", core_views.LoginView.as_view(), name="login"),
    path("keluar", core_views.logout_view, name="logout"),
    path("", reports_views.dashboard, name="dashboard"),
]
