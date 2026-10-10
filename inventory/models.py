from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import TenantModel


class StockTransaction(TenantModel):
    """
    Append-only stock ledger. Every stock change creates one row.
    Corrections are made with a new (reversing) row, never by editing an old one.
    """

    class TxnType(models.TextChoices):
        OPENING = "OPENING", "Opening stock"
        PURCHASE = "PURCHASE", "Purchase (stock in)"
        SALE = "SALE", "Sale"
        SALE_CANCEL = "SALE_CANCEL", "Sale cancelled"
        ADJUSTMENT = "ADJUSTMENT", "Manual adjustment"
        DAMAGE = "DAMAGE", "Damaged / expired"
        RETURN_IN = "RETURN_IN", "Customer return"
        RETURN_OUT = "RETURN_OUT", "Return to supplier"

    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="stock_transactions")
    txn_type = models.CharField(max_length=15, choices=TxnType.choices)
    quantity_change = models.IntegerField(help_text="Signed: positive = stock in, negative = stock out.")
    stock_after = models.IntegerField()
    reference_type = models.CharField(max_length=20, blank=True)
    reference_id = models.PositiveBigIntegerField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        constraints = [models.CheckConstraint(condition=~Q(quantity_change=0), name="stocktxn_nonzero_change")]
        indexes = [
            models.Index(fields=["business", "product", "-occurred_at"]),
            models.Index(fields=["business", "-occurred_at"]),
        ]

    def __str__(self):
        return f"{self.txn_type} {self.quantity_change:+d} {self.product_id}"


class Purchase(TenantModel):
    """Stock bought from a supplier (stock-in)."""

    supplier = models.ForeignKey("catalog.Supplier", on_delete=models.PROTECT, related_name="purchases")
    purchase_date = models.DateField(default=timezone.localdate)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-purchase_date", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(paid_amount__gte=0) & Q(paid_amount__lte=models.F("total_amount")), name="purchase_paid_within_total"),
        ]
        indexes = [models.Index(fields=["business", "-purchase_date"])]

    @property
    def balance(self):
        return self.total_amount - self.paid_amount

    def __str__(self):
        return f"Purchase #{self.pk}"


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="purchase_items")
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="purchaseitem_qty_positive")]

    @property
    def line_total(self):
        return self.quantity * self.unit_cost
