"""URL Audit Log Viewer (BR-14, AC-32.x)."""

from django.urls import path

from audit import views

app_name = "audit"

urlpatterns = [
    path("", views.audit_log_list, name="list"),
    path("<int:pk>", views.audit_log_detail, name="detail"),
    path("export", views.audit_export, name="export"),
]
