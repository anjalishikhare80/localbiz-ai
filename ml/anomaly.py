"""
Potentially-unusual-sale detection.

Isolation Forest is UNSUPERVISED: there are no confirmed-fraud labels, so there is no
accuracy figure to report. Output is a ranked list for a human to review, with the reason
(which feature is far from typical, using a robust median/MAD z-score).
"""
import numpy as np
import pandas as pd
from django.utils import timezone
from sklearn.ensemble import IsolationForest

from sales.models import Sale, SaleItem

MIN_SALES = 100
FEATURES = ["total", "item_count", "total_qty", "hour", "max_qty_ratio", "discount_ratio"]


def build_sale_features(business):
    sales = list(
        Sale.objects.for_business(business).filter(status="COMPLETED").values("id", "total", "sale_date")
    )
    if not sales:
        return pd.DataFrame()
    sdf = pd.DataFrame(sales).rename(columns={"id": "sale_id"})
    sdf["total"] = sdf["total"].astype(float)
    sdf["hour"] = sdf["sale_date"].apply(lambda d: timezone.localtime(d).hour)
    items = pd.DataFrame(list(
        SaleItem.objects.filter(sale__business=business, sale__status="COMPLETED")
        .values("sale_id", "product_id", "quantity", "unit_price", "discount")
    ))
    if items.empty:
        return pd.DataFrame()
    items["unit_price"] = items["unit_price"].astype(float)
    items["discount"] = items["discount"].astype(float)
    med = items.groupby("product_id")["quantity"].median().clip(lower=1)
    items["qty_ratio"] = items["quantity"] / items["product_id"].map(med)
    items["gross"] = items["quantity"] * items["unit_price"]
    agg = items.groupby("sale_id").agg(
        item_count=("product_id", "nunique"), total_qty=("quantity", "sum"),
        max_qty_ratio=("qty_ratio", "max"), discount=("discount", "sum"), gross=("gross", "sum"),
    )
    agg["discount_ratio"] = np.where(agg["gross"] > 0, agg["discount"] / agg["gross"], 0.0)
    return sdf.merge(agg[["item_count", "total_qty", "max_qty_ratio", "discount_ratio"]], left_on="sale_id", right_index=True)


def _robust_z(series):
    med = series.median()
    mad = (series - med).abs().median()
    if mad == 0:
        mad = series.std() or 1.0
        return (series - med) / mad
    return 0.6745 * (series - med) / mad


def _reason_text(feature, row, med):
    if feature == "total":
        return f"bill total {row['total']:,.0f} vs typical {med:,.0f}"
    if feature == "total_qty":
        return f"{int(row['total_qty'])} units in one sale vs typical {med:.0f}"
    if feature == "max_qty_ratio":
        return f"one item quantity is {row['max_qty_ratio']:.1f}x that product's usual quantity"
    if feature == "item_count":
        return f"{int(row['item_count'])} different products vs typical {med:.0f}"
    if feature == "discount_ratio":
        return f"discount is {row['discount_ratio'] * 100:.0f}% of the bill vs typical {med * 100:.0f}%"
    if feature == "hour":
        return f"sold at {int(row['hour']):02d}:00, an unusual hour"
    return feature


def detect(business, contamination=0.02):
    """Returns (flagged DataFrame with 'score' and 'reasons', info dict) or (None, None)."""
    df = build_sale_features(business)
    if len(df) < MIN_SALES:
        return None, None
    X = df[FEATURES].to_numpy(dtype=float)
    iso = IsolationForest(n_estimators=200, contamination=contamination, random_state=42).fit(X)
    df = df.assign(score=-iso.score_samples(X), flagged=iso.predict(X) == -1)
    zs = {f: _robust_z(df[f]) for f in FEATURES}
    meds = {f: float(df[f].median()) for f in FEATURES}
    flagged = df[df["flagged"]].copy()
    reasons = []
    for idx, row in flagged.iterrows():
        rs = [(abs(zs[f].loc[idx]), f) for f in FEATURES if abs(zs[f].loc[idx]) >= 3.5]
        rs.sort(reverse=True)
        texts = [_reason_text(f, row, meds[f]) for _, f in rs[:3]] or ["unusual combination of values compared with other sales"]
        reasons.append(texts)
    flagged["reasons"] = reasons
    return flagged, {"n_sales": int(len(df)), "n_flagged": int(len(flagged)), "contamination": contamination}
