from django import forms

from catalog.models import Product
from core.forms import StyledFormMixin

from .models import StockTransaction

ADJUST_CHOICES = [
    (StockTransaction.TxnType.ADJUSTMENT, "Stock count correction (+ or −)"),
    (StockTransaction.TxnType.DAMAGE, "Damaged / expired (removes stock)"),
    (StockTransaction.TxnType.RETURN_IN, "Customer return (adds stock)"),
    (StockTransaction.TxnType.RETURN_OUT, "Return to supplier (removes stock)"),
]


class StockAdjustForm(StyledFormMixin, forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.none())
    txn_type = forms.ChoiceField(choices=ADJUST_CHOICES, label="Type")
    quantity = forms.IntegerField(help_text="For corrections use a negative number to remove stock; for the other types enter a positive number.")
    note = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.for_business(business).filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("quantity") == 0:
            self.add_error("quantity", "Quantity cannot be zero.")
        return cleaned


class SupplierPaymentForm(StyledFormMixin, forms.Form):
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
