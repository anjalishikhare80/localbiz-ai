"""
Business analytics. All numbers come from the database (no invented data).

Profit definitions (documented in docs/ML_AND_ANALYTICS.md):
  gross profit  = sum over sold items of (unit_price*qty - discount - cost_price*qty)   [tax excluded]
  net profit    = gross profit - expenses in the same period
  Purchases are NOT expenses: stock bought is an asset until it is sold (cost_price snapshot).
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from catalog.models import Product
from core.utils import day_start, month_start, next_day_start
from customers.services import customers_with_stats
from finance.models import Expense
from sales.models import Sale, SaleItem

ZERO = Value(Decimal("0"), output_field=DecimalField(max_digits=14, decimal_places=2))
DEC = DecimalField(max_digits=14, decimal_places=2)


def completed_sales(business):
    return Sale.objects.for_business(business).filter(status=Sale.Status.COMPLETED)


def _profit_expr():
    return ExpressionWrapper(
        F("unit_price") * F("quantity") - F("discount") - F("cost_price") * F("quantity"), output_field=DEC
    )


def gross_profit(business, start, end):
    qs = SaleItem.objects.filter(sale__business=business, sale__status=Sale.Status.COMPLETED,
                                 sale__sale_date__gte=start, sale__sale_date__lt=end)
    return qs.aggregate(p=Coalesce(Sum(_profit_expr()), ZERO))["p"]


def expenses_total(business, start_date, end_date):
    qs = Expense.objects.for_business(business).filter(expense_date__gte=start_date, expense_date__lte=end_date)
    return qs.aggregate(t=Coalesce(Sum("amount"), ZERO))["t"]


def sales_total(business, start, end):
    qs = completed_sales(business).filter(sale_date__gte=start, sale_date__lt=end)
    return qs.aggregate(t=Coalesce(Sum("total"), ZERO), c=Count("id"))


def inventory_value(business):
    return Product.objects.for_business(business).filter(is_active=True).aggregate(
        v=Coalesce(Sum(ExpressionWrapper(F("current_stock") * F("purchase_price"), output_field=DEC)), ZERO)
    )["v"]


def receivables(business):
    return completed_sales(business).aggregate(
        v=Coalesce(Sum(ExpressionWrapper(F("total") - F("amount_paid"), output_field=DEC)), ZERO)
    )["v"]


def top_products(business, start, end, limit=5):
    return list(
        SaleItem.objects.filter(sale__business=business, sale__status=Sale.Status.COMPLETED,
                                sale__sale_date__gte=start, sale__sale_date__lt=end)
        .values("product_id", "product_name")
        .annotate(qty=Sum("quantity"), revenue=Sum("line_total"))
        .order_by("-revenue")[:limit]
    )


def sales_by_day(business, days=30):
    """[(date, total)] for the last ``days`` days including zero-sale days."""
    today = timezone.localdate()
    start_date = today - timedelta(days=days - 1)
    rows = (
        completed_sales(business).filter(sale_date__gte=day_start(start_date))
        .annotate(d=TruncDate("sale_date")).values("d").annotate(t=Sum("total"))
    )
    by_day = {r["d"]: r["t"] for r in rows}
    return [(start_date + timedelta(days=i), by_day.get(start_date + timedelta(days=i), Decimal("0"))) for i in range(days)]


def kpis(business, financial=True):
    today = timezone.localdate()
    t_start, t_end = day_start(today), next_day_start(today)
    m_start = month_start(today)
    today_s = sales_total(business, t_start, t_end)
    month_s = sales_total(business, m_start, t_end)
    data = {
        "today_sales": today_s["t"],
        "today_count": today_s["c"],
        "month_sales": month_s["t"],
        "month_count": month_s["c"],
        "outstanding": receivables(business),
        "low_stock_count": Product.objects.for_business(business).filter(is_active=True, current_stock__lte=F("reorder_level")).count(),
        "low_stock": list(Product.objects.for_business(business).filter(is_active=True, current_stock__lte=F("reorder_level")).order_by("current_stock")[:6]),
        "top_products": top_products(business, m_start, t_end),
        "recent_sales": list(completed_sales(business).select_related("customer", "invoice")[:6]),
        "financial": financial,
    }
    if financial:
        gp = gross_profit(business, m_start, t_end)
        exp = expenses_total(business, m_start.date(), today)
        data.update(month_gross_profit=gp, month_expenses=exp, month_net_profit=gp - exp, inventory_value=inventory_value(business))
    return data


def profit_loss(business, start_date, end_date):
    start, end = day_start(start_date), next_day_start(end_date)
    revenue = sales_total(business, start, end)["t"]
    gp = gross_profit(business, start, end)
    exp = expenses_total(business, start_date, end_date)
    return {"revenue": revenue, "gross_profit": gp, "expenses": exp, "net_profit": gp - exp}
