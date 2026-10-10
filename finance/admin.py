from django.contrib import admin

from .models import Expense, ExpenseCategory

admin.site.register(ExpenseCategory)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("expense_date", "business", "category", "amount")
    list_filter = ("business", "category")
