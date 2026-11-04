"""A view turns an HTTP request into the context used by an HTML template."""
from django.shortcuts import render
from django.utils import timezone

from .forms import MonthForm
from .sample_data import build_sample_dashboard, previous_month


def dashboard(request):
    today = timezone.localdate()
    current_month = today.replace(day=1)
    form = MonthForm(
        request.GET if "month" in request.GET else None,
        initial={"month": current_month},
    )
    valid = not form.is_bound or form.is_valid()
    selected_month = form.cleaned_data["month"] if form.is_bound and valid else current_month
    context = {
        "form": form,
        "selected_month": selected_month,
        "current_month": current_month,
        "previous_month": previous_month(today).replace(day=1),
        "is_partial": selected_month == current_month,
        "dashboard": build_sample_dashboard(selected_month, today) if valid else None,
        "selection_valid": valid,
    }
    return render(request, "listening/dashboard.html", context, status=200 if valid else 400)
