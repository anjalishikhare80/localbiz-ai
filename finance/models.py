import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import TenantModel

from .validators import validate_receipt


def receipt_path(instance, filename):
    """Randomised file name: the user-supplied name is never trusted or reused."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"receipts/{instance.business_id}/{uuid.uuid4().hex}.{ext}"


class ExpenseCategory(TenantModel):
    name = models.CharField(max_length=80)

    class Meta:
        verbose_name_plural = "expense categories"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], name="unique_expense_category_per_business")]

    def __str__(self):
        return self.name


class Expense(TenantModel):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        UPI = "UPI", "UPI"
        CARD = "CARD", "Card"
        BANK = "BANK", "Bank transfer"

    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    expense_date = models.DateField(default=timezone.localdate)
    description = models.CharField(max_length=255, blank=True)
    payment_method = models.CharField(max_length=10, choices=Method.choices, default=Method.CASH)
    receipt = models.FileField(upload_to=receipt_path, blank=True, validators=[validate_receipt])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-expense_date", "-id"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="expense_amount_positive")]
        indexes = [models.Index(fields=["business", "-expense_date"])]

    def __str__(self):
        return f"{self.category} {self.amount}"
