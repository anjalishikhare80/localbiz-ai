from django.contrib import admin

from .models import Category, Product, Supplier

admin.site.register(Category)
admin.site.register(Supplier)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "business", "current_stock", "selling_price", "is_active")
    list_filter = ("business", "is_active")
    search_fields = ("name", "sku", "barcode")
    readonly_fields = ("current_stock",)
