"""URL Pengaturan → Stok (S-16)."""

from django.urls import path

from stock import views

app_name = "stock"

urlpatterns = [
    path("stok", views.stock_settings, name="settings"),
    path("stok/<str:code>", views.stock_update, name="update"),
]
