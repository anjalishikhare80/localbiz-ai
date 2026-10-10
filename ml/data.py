"""Data preparation: turn database rows into dense daily time series (pandas)."""
from datetime import timedelta

import pandas as pd
from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from sales.models import Sale, SaleItem


def last_complete_day():
    """Yesterday: today is incomplete, so using it would teach the model false zeros."""
    return pd.Timestamp(timezone.localdate() - timedelta(days=1))


def _dense(df, value_col, end):
    frames = []
    for gid, g in df.groupby("group"):
        idx = pd.date_range(g["date"].min(), end, freq="D")
        s = g.set_index("date")[value_col].reindex(idx, fill_value=0)
        frames.append(pd.DataFrame({"group": gid, "date": idx, "y": s.values.astype(float)}))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["group", "date", "y"])


def product_daily_quantities(business):
    """Dense table [group=product_id, date, y=units sold] from each product's first sale to yesterday."""
    end = last_complete_day()
    rows = list(
        SaleItem.objects.filter(sale__business=business, sale__status=Sale.Status.COMPLETED)
        .annotate(d=TruncDate("sale__sale_date")).values("product_id", "d").annotate(q=Sum("quantity"))
    )
    if not rows:
        return pd.DataFrame(columns=["group", "date", "y"]), end
    df = pd.DataFrame(rows).rename(columns={"product_id": "group", "d": "date", "q": "value"})
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] <= end]
    if df.empty:
        return pd.DataFrame(columns=["group", "date", "y"]), end
    return _dense(df, "value", end), end


def business_daily_revenue(business):
    """Dense table [group=0, date, y=revenue (incl. tax)] from the first sale to yesterday."""
    end = last_complete_day()
    rows = list(
        Sale.objects.for_business(business).filter(status=Sale.Status.COMPLETED)
        .annotate(d=TruncDate("sale_date")).values("d").annotate(t=Sum("total"))
    )
    if not rows:
        return pd.DataFrame(columns=["group", "date", "y"]), end
    df = pd.DataFrame(rows).rename(columns={"d": "date", "t": "value"})
    df["value"] = df["value"].astype(float)
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] <= end]
    if df.empty:
        return pd.DataFrame(columns=["group", "date", "y"]), end
    df["group"] = 0
    return _dense(df, "value", end), end
