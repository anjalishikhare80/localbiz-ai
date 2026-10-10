from django.db import models


class TimeStampedModel(models.Model):
    """Adds created_at / updated_at to any model that inherits from it."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantQuerySet(models.QuerySet):
    def for_business(self, business):
        """The ONLY way application code should read business-owned rows."""
        return self.filter(business=business)


class TenantModel(TimeStampedModel):
    """
    Base class for every business-owned model.

    Tenant isolation rule: every query that serves a request goes through
    ``Model.objects.for_business(request.business)``. Child rows (e.g. SaleItem)
    are always reached through their tenant-scoped parent.
    """

    business = models.ForeignKey("businesses.Business", on_delete=models.CASCADE, related_name="+")

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True
