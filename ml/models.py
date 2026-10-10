from django.db import models

from core.models import TenantModel


class ModelVersion(TenantModel):
    """One training run. Predictions always point at the version that produced them."""

    class Kind(models.TextChoices):
        DEMAND = "DEMAND", "Product demand forecast"
        SALES = "SALES", "Sales forecast"
        SEGMENTS = "SEGMENTS", "Customer segmentation"
        ANOMALY = "ANOMALY", "Anomaly detection"
        ASSOC = "ASSOC", "Product associations"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    version = models.PositiveIntegerField()
    algorithm = models.CharField(max_length=60)
    trained_at = models.DateTimeField(auto_now_add=True)
    data_start = models.DateField(null=True, blank=True)
    data_end = models.DateField(null=True, blank=True)
    n_samples = models.PositiveIntegerField(default=0)
    metrics = models.JSONField(default=dict, blank=True)
    artifact_path = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-trained_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["business", "kind", "version"], name="unique_model_version")]

    def __str__(self):
        return f"{self.kind} v{self.version} ({self.algorithm})"


class DemandForecast(TenantModel):
    class Status(models.TextChoices):
        SUFFICIENT = "SUFFICIENT", "Stock sufficient"
        SHORTAGE_RISK = "SHORTAGE_RISK", "Potential shortage"
        INSUFFICIENT_DATA = "INSUFFICIENT_DATA", "Not enough history"

    model_version = models.ForeignKey(ModelVersion, on_delete=models.CASCADE, related_name="demand_forecasts")
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="demand_forecasts")
    horizon_days = models.PositiveIntegerField(default=7)
    predicted_demand = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    current_stock = models.IntegerField(default=0)
    days_of_cover = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    suggested_reorder = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices)

    class Meta:
        ordering = ["status", "-predicted_demand"]
        constraints = [models.UniqueConstraint(fields=["model_version", "product"], name="unique_forecast_per_version_product")]
        indexes = [models.Index(fields=["business", "model_version"])]


class SalesForecast(TenantModel):
    model_version = models.ForeignKey(ModelVersion, on_delete=models.CASCADE, related_name="sales_forecasts")
    forecast_date = models.DateField()
    predicted_amount = models.DecimalField(max_digits=14, decimal_places=2)
    lower = models.DecimalField(max_digits=14, decimal_places=2)
    upper = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["forecast_date"]
        constraints = [models.UniqueConstraint(fields=["model_version", "forecast_date"], name="unique_salesforecast_day")]


class CustomerSegment(TenantModel):
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="segments")
    recency_days = models.PositiveIntegerField()
    frequency = models.PositiveIntegerField()
    monetary = models.DecimalField(max_digits=14, decimal_places=2)
    r_score = models.PositiveSmallIntegerField()
    f_score = models.PositiveSmallIntegerField()
    m_score = models.PositiveSmallIntegerField()
    segment = models.CharField(max_length=20)
    kmeans_cluster = models.IntegerField(null=True, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["segment", "-monetary"]
        constraints = [models.UniqueConstraint(fields=["business", "customer"], name="unique_segment_per_customer")]


class AnomalyFlag(TenantModel):
    """A *potentially unusual* sale for a human to review - never a fraud verdict."""

    sale = models.ForeignKey("sales.Sale", on_delete=models.CASCADE, related_name="anomaly_flags")
    score = models.FloatField()
    reasons = models.JSONField(default=list)
    method = models.CharField(max_length=40, default="isolation_forest")
    reviewed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-score"]
        constraints = [models.UniqueConstraint(fields=["business", "sale"], name="unique_flag_per_sale")]


class ProductAssociation(TenantModel):
    product_a = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="+")
    product_b = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="+")
    pair_count = models.PositiveIntegerField()
    support = models.FloatField()
    confidence = models.FloatField()
    lift = models.FloatField()

    class Meta:
        ordering = ["-lift"]
        constraints = [models.UniqueConstraint(fields=["business", "product_a", "product_b"], name="unique_association_pair")]
