"""Report builders. Each returns (headers, rows) so the same data feeds HTML and CSV."""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, F, Sum
from django.db.models.functions import TruncDate, TruncMonth

from catalog.models import Product
from core.utils import day_start, next_day_start
from customers.services import customers_with_stats
from finance.models import Expense
from inventory.models import Purchase
from sales.models import Sale, SaleItem

from .services import profit_loss


def _range(start, end):
    return day_start(start), next_day_start(end)


def daily_sales(business, start, end):
    s, e = _range(start, end)
    rows = (
        Sale.objects.for_business(business).filter(status="COMPLETED", sale_date__gte=s, sale_date__lt=e)
        .annotate(d=TruncDate("sale_date")).values("d")
        .annotate(n=Count("id"), subtotal=Sum("subtotal"), tax=Sum("tax_amount"), total=Sum("total"), paid=Sum("amount_paid"))
        .order_by("d")
    )
    return ["Date", "Sales", "Subtotal", "Tax", "Total", "Collected"], [[r["d"], r["n"], r["subtotal"], r["tax"], r["total"], r["paid"]] for r in rows]


def monthly_sales(business, start, end):
    s, e = _range(start, end)
    rows = (
        Sale.objects.for_business(business).filter(status="COMPLETED", sale_date__gte=s, sale_date__lt=e)
        .annotate(m=TruncMonth("sale_date")).values("m").annotate(n=Count("id"), total=Sum("total")).order_by("m")
    )
    return ["Month", "Sales", "Total"], [[r["m"].strftime("%b %Y"), r["n"], r["total"]] for r in rows]


def profit_loss_report(business, start, end):
    pl = profit_loss(business, start, end)
    rows = [
        ["Revenue (excl. tax)", pl["revenue"] - sum_tax(business, start, end)],
        ["Gross profit (revenue − cost of goods sold)", pl["gross_profit"]],
        ["Expenses", pl["expenses"]],
        ["Estimated net profit", pl["net_profit"]],
    ]
    return ["Item", "Amount"], rows


def sum_tax(business, start, end):
    s, e = _range(start, end)
    return Sale.objects.for_business(business).filter(status="COMPLETED", sale_date__gte=s, sale_date__lt=e).aggregate(t=Sum("tax_amount"))["t"] or Decimal("0")


def inventory_report(business, start=None, end=None):
    rows = []
    for p in Product.objects.for_business(business).filter(is_active=True).select_related("category").order_by("name"):
        rows.append([p.name, p.sku, p.category.name if p.category else "", p.current_stock, p.purchase_price, p.selling_price, p.current_stock * p.purchase_price])
    return ["Product", "SKU", "Category", "Stock", "Cost", "Price", "Stock value"], rows


def low_stock_report(business, start=None, end=None):
    qs = Product.objects.for_business(business).filter(is_active=True, current_stock__lte=F("reorder_level")).select_related("supplier").order_by("current_stock")
    return ["Product", "SKU", "Stock", "Reorder level", "Minimum", "Supplier"], [
        [p.name, p.sku, p.current_stock, p.reorder_level, p.min_stock_level, p.supplier.name if p.supplier else ""] for p in qs
    ]


def customer_report(business, start=None, end=None):
    rows = [[c.name, c.phone, c.order_count, c.total_spent, c.outstanding, c.last_purchase] for c in customers_with_stats(business).order_by("-total_spent")]
    return ["Customer", "Phone", "Orders", "Total spent", "Outstanding", "Last purchase"], rows


def supplier_report(business, start, end):
    rows = (
        Purchase.objects.for_business(business).filter(purchase_date__gte=start, purchase_date__lte=end)
        .values("supplier__name").annotate(n=Count("id"), total=Sum("total_amount"), paid=Sum("paid_amount")).order_by("-total")
    )
    return ["Supplier", "Purchases", "Total purchased", "Paid", "Outstanding"], [[r["supplier__name"], r["n"], r["total"], r["paid"], r["total"] - r["paid"]] for r in rows]


def expense_report(business, start, end):
    rows = (
        Expense.objects.for_business(business).filter(expense_date__gte=start, expense_date__lte=end)
        .values("category__name").annotate(n=Count("id"), total=Sum("amount")).order_by("-total")
    )
    return ["Category", "Entries", "Total"], [[r["category__name"], r["n"], r["total"]] for r in rows]


def tax_report(business, start, end):
    s, e = _range(start, end)
    rows = (
        Sale.objects.for_business(business).filter(status="COMPLETED", sale_date__gte=s, sale_date__lt=e)
        .annotate(m=TruncMonth("sale_date")).values("m").annotate(taxable=Sum("subtotal"), tax=Sum("tax_amount")).order_by("m")
    )
    return ["Month", "Taxable sales", "Tax collected"], [[r["m"].strftime("%b %Y"), r["taxable"], r["tax"]] for r in rows]


# slug -> (title, builder, permission, needs_dates)
REPORTS = {
    "daily-sales": ("Daily sales", daily_sales, "reports.view", True),
    "monthly-sales": ("Monthly sales", monthly_sales, "reports.view", True),
    "profit-loss": ("Profit & loss summary", profit_loss_report, "reports.financial", True),
    "inventory": ("Inventory report", inventory_report, "reports.view", False),
    "low-stock": ("Low-stock report", low_stock_report, "reports.view", False),
    "customers": ("Customer report", customer_report, "reports.view", False),
    "suppliers": ("Supplier report", supplier_report, "reports.view", True),
    "expenses": ("Expense report", expense_report, "reports.financial", True),
    "tax": ("Tax summary (simple)", tax_report, "reports.financial", True),
}
