"""
Customer segmentation: RFM scoring (primary, explainable) + K-Means (data-driven comparison).

RFM
  Recency   = days since last purchase        (lower is better)
  Frequency = number of completed sales
  Monetary  = total spent
Each is scored 1-5 by quantile rank. Segments are assigned by transparent rules.

K-Means
  Features are log1p-transformed (spend is heavily skewed) and standardised (otherwise the
  rupee amount would dominate distance). k is chosen from 2..6 by silhouette score.
  Clusters are NOT given invented names: each cluster is shown with its real average R/F/M.
"""
import numpy as np
import pandas as pd
from django.db.models import Count, Max, Sum
from django.utils import timezone
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from sales.models import Sale

MIN_CUSTOMERS = 10


def _score(series, ascending=True):
    ranks = series.rank(method="first", ascending=ascending)
    return (pd.qcut(ranks, 5, labels=False) + 1).astype(int)


def label_segment(recency_days, r, f, m):
    if recency_days > 90:
        return "Inactive"
    if r <= 2 and f >= 3:
        return "At Risk"
    if m >= 4 and f >= 3 and r >= 3:
        return "High Value"
    if f >= 4 and r >= 3:
        return "Loyal"
    if f >= 3 or m >= 3:
        return "Regular"
    return "Occasional"


def compute_rfm(business, now=None):
    now = now or timezone.now()
    rows = list(
        Sale.objects.for_business(business).filter(status="COMPLETED", customer__isnull=False)
        .values("customer_id").annotate(last=Max("sale_date"), freq=Count("id"), monetary=Sum("total"))
    )
    if len(rows) < MIN_CUSTOMERS:
        return None
    df = pd.DataFrame(rows)
    df["recency"] = df["last"].apply(lambda d: max((now - d).days, 0))
    df["monetary"] = df["monetary"].astype(float)
    # recency: SMALLER is better, so rank descending to give recent customers the higher score
    df["R"] = _score(df["recency"], ascending=False)
    df["F"] = _score(df["freq"])
    df["M"] = _score(df["monetary"])
    df["segment"] = [label_segment(r_days, r, f, m) for r_days, r, f, m in zip(df["recency"], df["R"], df["F"], df["M"])]
    return df


def run_kmeans(df):
    """Returns (cluster labels, info dict) or (None, None) when the data is too small."""
    if len(df) < 15:
        return None, None
    X = np.log1p(df[["recency", "freq", "monetary"]].to_numpy(dtype=float))
    X = StandardScaler().fit_transform(X)
    best = None
    for k in range(2, min(6, len(df) // 4) + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(X)
        if len(set(km.labels_)) < 2:
            continue
        score = float(silhouette_score(X, km.labels_))
        if best is None or score > best[0]:
            best = (score, k, km.labels_)
    if best is None:
        return None, None
    score, k, labels = best
    work = df.assign(cluster=labels)
    clusters = []
    for cid, g in work.groupby("cluster"):
        clusters.append({
            "cluster": int(cid), "size": int(len(g)),
            "avg_recency_days": round(float(g["recency"].mean()), 1),
            "avg_frequency": round(float(g["freq"].mean()), 1),
            "avg_monetary": round(float(g["monetary"].mean()), 2),
        })
    return labels, {"k": k, "silhouette": round(score, 3), "clusters": clusters,
                    "note": "k chosen by highest silhouette score among 2..6"}
