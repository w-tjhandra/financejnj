"""URL transaksi ledger: form (S-05), detail (S-06), dan hapus (S-07)."""

from django.urls import path

from ledger import views

urlpatterns = [
    path("baru", views.transaction_create, name="transaction_create"),
    path("field-item", views.transaction_item_fields, name="transaction_item_fields"),
    path("opsi-item", views.transaction_item_options, name="transaction_item_options"),
    path("<int:pk>", views.transaction_detail, name="transaction_detail"),
    path("<int:pk>/ubah", views.transaction_update, name="transaction_update"),
    path("<int:pk>/hapus", views.transaction_delete, name="transaction_delete"),
]
