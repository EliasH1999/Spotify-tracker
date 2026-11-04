from django import forms
from django.utils import timezone


class MonthForm(forms.Form):
    month = forms.DateField(
        label="Explore a month",
        input_formats=["%Y-%m"],
        widget=forms.DateInput(format="%Y-%m", attrs={"type": "month"}),
        error_messages={"invalid": "Enter a valid month, such as 2026-11."},
    )

    def clean_month(self):
        month = self.cleaned_data["month"].replace(day=1)
        if month > timezone.localdate().replace(day=1):
            raise forms.ValidationError("Choose this month or an earlier month.")
        return month
