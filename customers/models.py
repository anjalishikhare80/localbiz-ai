from django.db import models
from django.db.models import Q

from core.models import TenantModel


class Customer(TenantModel):
    """
    Spending / outstanding balance are NOT stored: they are computed from sales
    (see customers.services.customers_with_stats) so they can never drift.
    """

    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["business", "phone"], condition=~Q(phone=""), name="unique_customer_phone_per_business"),
        ]
        indexes = [models.Index(fields=["business", "name"])]

    def __str__(self):
        return self.name
