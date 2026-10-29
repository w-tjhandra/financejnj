"""Dashboard (S-03). Untuk sementara hanya kerangka; query menyusul T-007."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    return render(request, "reports/dashboard.html")
