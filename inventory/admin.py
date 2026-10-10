from django.contrib import admin

from .models import Purchase, PurchaseItem, StockTransaction


@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "business", "product", "txn_type", "quantity_change", "stock_after")
    list_filter = ("txn_type", "business")
    readonly_fields = [f.name for f in StockTransaction._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 0


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("id", "business", "supplier", "purchase_date", "total_amount", "paid_amount")
    inlines = [PurchaseItemInline]
