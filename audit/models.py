from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """
    Append-only record of important actions.
    business is nullable because e.g. a login happens before a business is chosen.
    """

    business = models.ForeignKey("businesses.Business", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=60)
    entity_type = models.CharField(max_length=60, blank=True)
    entity_id = models.CharField(max_length=40, blank=True)
    entity_repr = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["business", "-created_at"])]

    def __str__(self):
        return f"{self.action} {self.entity_type}#{self.entity_id}"
