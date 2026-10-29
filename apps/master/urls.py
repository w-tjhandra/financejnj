"""URL Pengaturan master: kategori, item, dan guard satuan stok."""

from django.urls import path

from master import views

app_name = "master"

urlpatterns = [
    path("kategori", views.category_list, name="category_list"),
    path("kategori/<int:pk>/ubah", views.category_update, name="category_update"),
    path("kategori/<int:pk>/nonaktifkan", views.category_deactivate, name="category_deactivate"),
    path("kategori/<int:pk>/aktifkan", views.category_activate, name="category_activate"),
    path("kategori/<int:pk>/hapus", views.category_delete, name="category_delete"),
    path("item", views.item_list, name="item_list"),
    path("item/<int:pk>/ubah", views.item_update, name="item_update"),
    path("item/<int:pk>/nonaktifkan", views.item_deactivate, name="item_deactivate"),
    path("item/<int:pk>/aktifkan", views.item_activate, name="item_activate"),
    path("item/<int:pk>/hapus", views.item_delete, name="item_delete"),
    path("stok/<str:code>/satuan", views.stock_unit_update, name="stock_unit_update"),
]
