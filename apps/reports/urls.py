"""URL Rekap: harian (S-10), mingguan (S-11), bulanan (S-12), tahunan (S-13)."""

from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("harian", views.daily_recap_view, name="daily_recap"),
    path("mingguan", views.weekly_recap_view, name="weekly_recap"),
    path("bulanan", views.monthly_recap_view, name="monthly_recap"),
    path("tahunan", views.yearly_recap_view, name="yearly_recap"),
]
