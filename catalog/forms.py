from django import forms

from core.forms import TenantModelForm

from .models import Category, Product, Supplier


class CategoryForm(TenantModelForm):
    class Meta:
        model = Category
        fields = ["name"]


class SupplierForm(TenantModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_person", "phone", "email", "address", "is_active"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}


class ProductForm(TenantModelForm):
    opening_stock = forms.IntegerField(min_value=0, required=False, initial=0, help_text="Stock on hand right now (recorded in the stock ledger).")

    class Meta:
        model = Product
        fields = [
            "name", "sku", "barcode", "category", "supplier", "unit",
            "purchase_price", "selling_price", "min_stock_level", "reorder_level", "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            del self.fields["opening_stock"]  # stock is changed via the Inventory module only
