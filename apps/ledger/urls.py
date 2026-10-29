"""URL transaksi ledger: daftar (S-04), form (S-05), detail (S-06), hapus (S-07)."""

from django.urls import path

from ledger import views

urlpatterns = [
    path("", views.transaction_list, name="transaction_list"),
    path("baru", views.transaction_create, name="transaction_create"),
    path("field-item", views.transaction_item_fields, name="transaction_item_fields"),
    path("opsi-item", views.transaction_item_options, name="transaction_item_options"),
    path("<int:pk>", views.transaction_detail, name="transaction_detail"),
    path("<int:pk>/ubah", views.transaction_update, name="transaction_update"),
    path("<int:pk>/hapus", views.transaction_delete, name="transaction_delete"),
]
