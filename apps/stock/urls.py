"""URL Stok: pengaturan (S-16), input harian (S-08), penyesuaian (S-09)."""

from django.urls import path

from stock import views

app_name = "stock"

urlpatterns = [
    path("", views.stock_settings, name="settings"),
    path("harian", views.daily_stock, name="daily"),
    path("penyesuaian", views.stock_adjustment, name="adjustment"),
    path("<str:code>", views.stock_update, name="update"),
]
