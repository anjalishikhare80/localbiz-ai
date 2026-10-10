from django.db import models
from django.db.models import Q

from core.models import TenantModel


class Category(TenantModel):
    name = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], name="unique_category_per_business")]

    def __str__(self):
        return self.name


class Supplier(TenantModel):
    name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], name="unique_supplier_per_business")]

    def __str__(self):
        return self.name


class Product(TenantModel):
    """
    current_stock is a CACHE of the stock ledger (inventory.StockTransaction).
    It must only be changed through inventory.services.adjust_stock().
    Products are soft-deleted (is_active) so sales history stays intact.
    """

    name = models.CharField(max_length=150)
    sku = models.CharField("SKU", max_length=50)
    barcode = models.CharField(max_length=64, blank=True)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products")
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="products")
    unit = models.CharField(max_length=20, default="pcs")
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    current_stock = models.IntegerField(default=0)
    min_stock_level = models.PositiveIntegerField(default=0, help_text="Stock you never want to fall below.")
    reorder_level = models.PositiveIntegerField(default=0, help_text="When stock reaches this level, reorder.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["business", "sku"], name="unique_sku_per_business"),
            models.UniqueConstraint(
                fields=["business", "barcode"], condition=~Q(barcode=""), name="unique_barcode_per_business"
            ),
            models.CheckConstraint(condition=Q(current_stock__gte=0), name="product_stock_non_negative"),
            models.CheckConstraint(condition=Q(selling_price__gte=0, purchase_price__gte=0), name="product_prices_non_negative"),
        ]
        indexes = [models.Index(fields=["business", "is_active"]), models.Index(fields=["business", "name"])]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    @property
    def is_low_stock(self):
        return self.current_stock <= self.reorder_level
