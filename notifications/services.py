from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from catalog.models import Product
from customers.services import customers_with_stats

from .models import Notification


def _notify(business, *, kind, level, title, message, key):
    exists = Notification.objects.for_business(business).filter(dedupe_key=key, is_read=False).exists()
    if exists:
        return 0
    Notification.objects.create(business=business, kind=kind, level=level, title=title, message=message, dedupe_key=key)
    return 1


def generate_alerts(business):
    """Create in-app alerts from real data. Safe to run repeatedly (no duplicate unread alerts)."""
    created = 0
    # 1) low stock
    for p in Product.objects.for_business(business).filter(is_active=True, current_stock__lte=F("reorder_level")):
        level = Notification.Level.DANGER if p.current_stock <= p.min_stock_level else Notification.Level.WARNING
        created += _notify(
            business, kind=Notification.Kind.LOW_STOCK, level=level, key=f"low-{p.pk}",
            title=f"Low stock: {p.name}",
            message=f"{p.current_stock} {p.unit} left (reorder level {p.reorder_level}).",
        )
    # 2) forecast-based shortage
    from ml.models import DemandForecast

    for f in DemandForecast.objects.for_business(business).filter(
        model_version__is_active=True, status=DemandForecast.Status.SHORTAGE_RISK
    ).select_related("product"):
        created += _notify(
            business, kind=Notification.Kind.FORECAST, level=Notification.Level.WARNING,
            key=f"forecast-{f.product_id}-{f.model_version_id}", title=f"Possible shortage: {f.product.name}",
            message=f"Forecast demand for the next {f.horizon_days} days is {f.predicted_demand:.0f}; stock is {f.current_stock}.",
        )
    # 3) overdue customer payments (balance owed, oldest unpaid sale older than 30 days)
    from sales.models import Sale

    cutoff = timezone.now() - timedelta(days=30)
    for c in customers_with_stats(business).filter(outstanding__gt=0):
        oldest = (
            Sale.objects.for_business(business).filter(customer=c, status="COMPLETED", amount_paid__lt=F("total"))
            .order_by("sale_date").first()
        )
        if oldest and oldest.sale_date < cutoff:
            created += _notify(
                business, kind=Notification.Kind.PAYMENT, level=Notification.Level.WARNING, key=f"pay-{c.pk}",
                title=f"Payment overdue: {c.name}", message=f"Owes {c.outstanding:,.2f}; oldest unpaid bill is from {oldest.sale_date:%d %b %Y}.",
            )
    return created
