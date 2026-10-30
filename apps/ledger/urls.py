"""URL transaksi ledger: daftar, form, detail, hapus, duplikat, lampiran, PDF investor."""

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
    path("<int:pk>/duplikat", views.transaction_duplicate, name="transaction_duplicate"),
    # Attachments
    path("<int:pk>/lampiran/tambah", views.attachment_upload, name="attachment_upload"),
    path("<int:pk>/lampiran/<int:att_pk>/hapus", views.attachment_delete, name="attachment_delete"),
    path(
        "<int:pk>/lampiran/<int:att_pk>/unduh",
        views.attachment_download,
        name="attachment_download",
    ),
    # PDF Investor Report
    path("pdf/investor", views.investor_pdf, name="investor_pdf"),
]
