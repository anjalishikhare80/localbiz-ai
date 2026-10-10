from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from core.models import TenantModel


class Sale(TenantModel):
    class Status(models.TextChoices):
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        UPI = "UPI", "UPI"
        CARD = "CARD", "Card"
        BANK = "BANK", "Bank transfer"

    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="sales")
    sale_date = models.DateTimeField(default=timezone.now)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # cached sum of Payment rows
    payment_method = models.CharField(max_length=10, choices=Method.choices, default=Method.CASH)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.COMPLETED)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-sale_date", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_paid__gte=0) & Q(amount_paid__lte=F("total")), name="sale_paid_within_total"),
            models.CheckConstraint(condition=Q(total__gte=0), name="sale_total_non_negative"),
        ]
        indexes = [
            models.Index(fields=["business", "-sale_date"]),
            models.Index(fields=["business", "status", "-sale_date"]),
            models.Index(fields=["business", "customer"]),
        ]

    @property
    def balance(self):
        return self.total - self.amount_paid

    @property
    def payment_status(self):
        if self.status == self.Status.CANCELLED:
            return "Cancelled"
        if self.amount_paid >= self.total:
            return "Paid"
        return "Partial" if self.amount_paid > 0 else "Unpaid"

    @property
    def invoice_number(self):
        inv = getattr(self, "invoice", None)
        return inv.number if inv else ""

    def __str__(self):
        return f"Sale #{self.pk}"


class SaleItem(models.Model):
    """Prices are SNAPSHOTS: later price edits never change historical sales or profit."""

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="sale_items")
    product_name = models.CharField(max_length=150)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # total discount on this line
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="saleitem_qty_positive"),
            models.CheckConstraint(condition=Q(discount__gte=0), name="saleitem_discount_non_negative"),
        ]
        indexes = [models.Index(fields=["product"])]


class Payment(TenantModel):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="payments")
    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=10, choices=Sale.Method.choices, default=Sale.Method.CASH)
    paid_at = models.DateTimeField(default=timezone.now)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-paid_at", "-id"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive")]


class Invoice(TenantModel):
    sale = models.OneToOneField(Sale, on_delete=models.PROTECT, related_name="invoice")
    number = models.CharField(max_length=30)
    issued_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "number"], name="unique_invoice_number_per_business")]

    def __str__(self):
        return self.number
