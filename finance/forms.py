from django import forms

from core.forms import TenantModelForm

from .models import Expense, ExpenseCategory


class ExpenseCategoryForm(TenantModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ["name"]


class ExpenseForm(TenantModelForm):
    class Meta:
        model = Expense
        fields = ["category", "amount", "expense_date", "description", "payment_method", "receipt"]
        widgets = {"expense_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
