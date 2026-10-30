"""URL Rekap: harian (S-10), mingguan (S-11), bulanan (S-12), tahunan (S-13) + Export XLSX."""

from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("harian", views.daily_recap_view, name="daily_recap"),
    path("mingguan", views.weekly_recap_view, name="weekly_recap"),
    path("bulanan", views.monthly_recap_view, name="monthly_recap"),
    path("tahunan", views.yearly_recap_view, name="yearly_recap"),
    # Export XLSX
    path("harian/export", views.export_daily_xlsx, name="export_daily"),
    path("mingguan/export", views.export_weekly_xlsx, name="export_weekly"),
    path("bulanan/export", views.export_monthly_xlsx, name="export_monthly"),
    path("tahunan/export", views.export_yearly_xlsx, name="export_yearly"),
]
