from django.db import models

from core.models import TenantModel


class Notification(TenantModel):
    class Kind(models.TextChoices):
        LOW_STOCK = "LOW_STOCK", "Low stock"
        FORECAST = "FORECAST", "Forecast alert"
        PAYMENT = "PAYMENT", "Payment reminder"
        INFO = "INFO", "Information"

    class Level(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        DANGER = "danger", "Critical"

    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.INFO)
    level = models.CharField(max_length=8, choices=Level.choices, default=Level.INFO)
    title = models.CharField(max_length=150)
    message = models.TextField(blank=True)
    dedupe_key = models.CharField(max_length=80, blank=True, help_text="Prevents repeating the same unread alert.")
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["business", "is_read", "-created_at"])]

    def __str__(self):
        return self.title
