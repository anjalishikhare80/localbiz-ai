from django.conf import settings
from django.db import models, transaction

from core.models import TimeStampedModel


class Business(TimeStampedModel):
    """A tenant. Every business-owned row in the database points here."""

    class BusinessType(models.TextChoices):
        STATIONERY = "STATIONERY", "Stationery shop"
        GROCERY = "GROCERY", "Grocery store"
        CLOTHING = "CLOTHING", "Clothing shop"
        ELECTRONICS = "ELECTRONICS", "Electronics shop"
        BAKERY = "BAKERY", "Bakery"
        HARDWARE = "HARDWARE", "Hardware shop"
        OTHER = "OTHER", "Other"

    name = models.CharField(max_length=150)
    business_type = models.CharField(max_length=20, choices=BusinessType.choices, default=BusinessType.OTHER)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    tax_id = models.CharField("GSTIN / tax ID", max_length=30, blank=True)
    currency = models.CharField(max_length=3, default="INR")
    tax_rate = models.DecimalField("Tax rate (%)", max_digits=5, decimal_places=2, default=0)
    invoice_prefix = models.CharField(max_length=10, default="INV")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "businesses"
        constraints = [
            models.CheckConstraint(condition=models.Q(tax_rate__gte=0, tax_rate__lte=100), name="business_tax_rate_0_100"),
        ]

    def __str__(self):
        return self.name


class BusinessMember(TimeStampedModel):
    """
    Links a User to a Business with a role.

    The role lives HERE (not on User) because the same person can belong to
    several businesses with different roles.
    """

    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        MANAGER = "MANAGER", "Manager"
        EMPLOYEE = "EMPLOYEE", "Employee"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="members")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.EMPLOYEE)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "business"], name="unique_member_per_business")]

    def __str__(self):
        return f"{self.user} @ {self.business} ({self.role})"


class BusinessSequence(models.Model):
    """Race-free per-business counters (used for invoice numbers)."""

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="+")
    key = models.CharField(max_length=40)
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "key"], name="unique_sequence_key")]

    @classmethod
    def next_value(cls, business, key):
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(business=business, key=key)
            seq.last_value += 1
            seq.save(update_fields=["last_value"])
            return seq.last_value
