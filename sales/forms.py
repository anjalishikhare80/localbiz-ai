from django import forms

from core.forms import StyledFormMixin

from .models import Sale


class PaymentForm(StyledFormMixin, forms.Form):
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
    method = forms.ChoiceField(choices=Sale.Method.choices)
    note = forms.CharField(max_length=255, required=False)
