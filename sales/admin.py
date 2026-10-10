from django.contrib import admin

from .models import Invoice, Payment, Sale, SaleItem


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("id", "business", "sale_date", "total", "amount_paid", "status")
    list_filter = ("business", "status")
    inlines = [SaleItemInline]


admin.site.register(Payment)
admin.site.register(Invoice)
