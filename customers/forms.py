from django import forms

from core.forms import StyledFormMixin, TenantModelForm

from .models import Customer


class CustomerForm(TenantModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "email", "address", "is_active"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}


class CustomerPaymentForm(StyledFormMixin, forms.Form):
    METHODS = [("CASH", "Cash"), ("UPI", "UPI"), ("CARD", "Card"), ("BANK", "Bank transfer")]
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
    method = forms.ChoiceField(choices=METHODS)
