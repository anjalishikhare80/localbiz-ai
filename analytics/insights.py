"""
Rule-based business insights, computed from real data only.
Every insight is a sentence plus a severity; nothing here is invented or random.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, F, Max, Sum
from django.utils import timezone

from catalog.models import Product
from core.utils import day_start
from customers.services import customers_with_stats
from sales.models import Sale, SaleItem


def _pct(new, old):
    if not old:
        return None
    return float((Decimal(new) - Decimal(old)) / Decimal(old) * 100)


def generate_insights(business):
    now = timezone.now()
    today = timezone.localdate()
    out = []

    # 1) revenue trend: last 4 weeks vs the 4 weeks before
    cur_start, prev_start = day_start(today - timedelta(days=28)), day_start(today - timedelta(days=56))
    base = Sale.objects.for_business(business).filter(status="COMPLETED")
    cur = base.filter(sale_date__gte=cur_start).aggregate(t=Sum("total"))["t"] or 0
    prev = base.filter(sale_date__gte=prev_start, sale_date__lt=cur_start).aggregate(t=Sum("total"))["t"] or 0
    change = _pct(cur, prev)
    if change is not None:
        direction = "increased" if change >= 0 else "decreased"
        out.append({"severity": "success" if change >= 0 else "warning",
                    "text": f"Total sales {direction} by {abs(change):.0f}% over the last four weeks compared with the four weeks before."})

    # 2) product weekly trends (qty), last 4 complete 7-day windows
    items = SaleItem.objects.filter(sale__business=business, sale__status="COMPLETED", sale__sale_date__gte=day_start(today - timedelta(days=56)))
    weekly = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0, 0])
    names = {}
    for row in items.values("product_id", "product_name", "quantity", "sale__sale_date"):
        age_days = (now - row["sale__sale_date"]).days
        idx = age_days // 7
        if 0 <= idx < 8:
            weekly[row["product_id"]][idx] += row["quantity"]
            names[row["product_id"]] = row["product_name"]
    for pid, w in weekly.items():
        recent4 = list(reversed(w[:4]))  # oldest -> newest
        if recent4[0] > recent4[1] > recent4[2] > recent4[3] and recent4[0] >= 4:
            out.append({"severity": "warning", "text": f"{names[pid]} sales have declined for three consecutive weeks ({recent4[0]} → {recent4[3]} units per week)."})
        prev4, cur4 = sum(w[4:8]), sum(w[0:4])
        ch = _pct(cur4, prev4)
        if ch is not None and ch >= 25 and prev4 >= 10:
            out.append({"severity": "success", "text": f"{names[pid]} sales increased by {ch:.0f}% over the last four weeks."})

    # 3) stock cover from recent demand
    sold_28 = dict(
        SaleItem.objects.filter(sale__business=business, sale__status="COMPLETED", sale__sale_date__gte=day_start(today - timedelta(days=28)))
        .values_list("product_id").annotate(q=Sum("quantity"))
    )
    for p in Product.objects.for_business(business).filter(is_active=True):
        q = sold_28.get(p.id, 0)
        if q:
            daily = q / 28
            days_left = p.current_stock / daily
            if days_left <= 7:
                out.append({"severity": "danger" if days_left <= 3 else "warning",
                            "text": f"{p.name} may fall below zero stock in about {max(days_left, 0):.0f} day(s) at the recent selling rate ({p.current_stock} left)."})

    # 4) slow-moving stock: stock on hand but no sale for 60 days
    last_sale = dict(
        SaleItem.objects.filter(sale__business=business, sale__status="COMPLETED").values_list("product_id").annotate(m=Max("sale__sale_date"))
    )
    stuck_value, stuck_count = Decimal("0"), 0
    for p in Product.objects.for_business(business).filter(is_active=True, current_stock__gt=0):
        last = last_sale.get(p.id) or p.created_at  # never sold: count from when the product was added
        if (now - last).days >= 60:
            stuck_count += 1
            stuck_value += p.current_stock * p.purchase_price
    if stuck_count:
        out.append({"severity": "info", "text": f"{stuck_count} product(s) have not sold in 60+ days; about {stuck_value:,.0f} is tied up in this stock."})

    # 5) customers
    inactive = customers_with_stats(business).filter(order_count__gt=0, last_purchase__lt=now - timedelta(days=60)).count()
    if inactive:
        out.append({"severity": "info", "text": f"{inactive} customer(s) have not purchased in the last 60 days."})
    owing = customers_with_stats(business).filter(outstanding__gt=0)
    n_owing = owing.count()
    if n_owing:
        total_owed = sum((c.outstanding for c in owing), Decimal("0"))
        out.append({"severity": "warning", "text": f"{n_owing} customer(s) owe a total of {total_owed:,.0f}."})

    order = {"danger": 0, "warning": 1, "info": 2, "success": 3}
    out.sort(key=lambda i: order.get(i["severity"], 9))
    return out
