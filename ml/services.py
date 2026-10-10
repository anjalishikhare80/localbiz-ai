"""
ML pipeline orchestration:  data -> features -> train/evaluate -> ModelVersion -> saved artifact -> prediction tables.

Training is NEVER triggered by opening a page. It runs from `manage.py train_models`,
a Celery task, or the owner's "Retrain now" button.
"""
import math
from decimal import Decimal
from pathlib import Path

import joblib
from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from catalog.models import Product
from customers.models import Customer

from . import anomaly, data, forecasting, recommendations, segmentation
from .models import (AnomalyFlag, CustomerSegment, DemandForecast, ModelVersion, ProductAssociation, SalesForecast)

DEMAND_HORIZON = 7
SALES_HORIZON = 14


def _new_version(business, kind, algorithm, **extra):
    last = ModelVersion.objects.for_business(business).filter(kind=kind).aggregate(m=Max("version"))["m"] or 0
    ModelVersion.objects.for_business(business).filter(kind=kind, is_active=True).update(is_active=False)
    return ModelVersion.objects.create(business=business, kind=kind, version=last + 1, algorithm=algorithm, **extra)


def _save_artifact(business, kind, version, payload):
    folder = Path(settings.ML_ARTIFACT_DIR) / str(business.pk)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{kind.lower()}_v{version}.joblib"
    joblib.dump(payload, path)
    return str(path)


def _result_metrics(result):
    return {
        "horizon_days": None, "holdout_days": result["holdout_days"], "train_rows": result["train_rows"],
        "test_rows": result["test_rows"], "selected": result["selected"], "selected_by": result["selected_by"],
        "candidates": result["metrics"],
        "n_series": len(result["eligible"]),
    }


@transaction.atomic
def run_demand_forecast(business):
    df, end = data.product_daily_quantities(business)
    result = forecasting.evaluate_and_forecast(df, DEMAND_HORIZON, select_by="block_mae")
    if result is None:
        return {"status": "insufficient_data", "message": "Not enough sales history to forecast demand (need roughly 3+ months)."}
    metrics = _result_metrics(result)
    metrics["horizon_days"] = DEMAND_HORIZON
    version = _new_version(
        business, ModelVersion.Kind.DEMAND, result["selected"], data_start=df["date"].min().date(), data_end=result["data_end"],
        n_samples=result["train_rows"] + result["test_rows"], metrics=metrics,
    )
    if result["model"] is not None:
        version.artifact_path = _save_artifact(business, "DEMAND", version.version, {"model": result["model"], "horizon": DEMAND_HORIZON})
        version.save(update_fields=["artifact_path"])
    totals = result["forecast"].groupby("group")["yhat"].sum()
    created = 0
    for p in Product.objects.for_business(business).filter(is_active=True):
        if p.id in totals.index:
            demand = float(totals[p.id])
            daily = demand / DEMAND_HORIZON
            cover = (p.current_stock / daily) if daily > 0 else None
            status = DemandForecast.Status.SHORTAGE_RISK if p.current_stock < demand else DemandForecast.Status.SUFFICIENT
            reorder = max(0, math.ceil(demand + p.min_stock_level - p.current_stock)) if status == DemandForecast.Status.SHORTAGE_RISK else 0
            DemandForecast.objects.create(
                business=business, model_version=version, product=p, horizon_days=DEMAND_HORIZON,
                predicted_demand=Decimal(str(round(demand, 2))), current_stock=p.current_stock,
                days_of_cover=Decimal(str(round(cover, 1))) if cover is not None and cover < 9999 else None,
                suggested_reorder=reorder, status=status,
            )
        else:
            DemandForecast.objects.create(
                business=business, model_version=version, product=p, horizon_days=DEMAND_HORIZON,
                current_stock=p.current_stock, status=DemandForecast.Status.INSUFFICIENT_DATA,
            )
        created += 1
    return {"status": "ok", "version": version.version, "selected": result["selected"], "products": created}


@transaction.atomic
def run_sales_forecast(business):
    df, end = data.business_daily_revenue(business)
    result = forecasting.evaluate_and_forecast(df, SALES_HORIZON, min_test_rows=14)
    if result is None:
        return {"status": "insufficient_data", "message": "Not enough sales history to forecast sales."}
    metrics = _result_metrics(result)
    metrics.update(horizon_days=SALES_HORIZON,
                   interval_note="Range = forecast + 10th/90th percentile of the model's errors on held-out days (empirical, not a statistical confidence level).")
    version = _new_version(business, ModelVersion.Kind.SALES, result["selected"], data_start=df["date"].min().date(),
                           data_end=result["data_end"], n_samples=result["train_rows"] + result["test_rows"], metrics=metrics)
    if result["model"] is not None:
        version.artifact_path = _save_artifact(business, "SALES", version.version, {"model": result["model"], "horizon": SALES_HORIZON})
        version.save(update_fields=["artifact_path"])
    lo, hi = result["residual_q"]
    for _, row in result["forecast"].iterrows():
        yhat = float(row["yhat"])
        SalesForecast.objects.create(
            business=business, model_version=version, forecast_date=row["date"].date(),
            predicted_amount=Decimal(str(round(yhat, 2))),
            lower=Decimal(str(round(max(yhat + lo, 0), 2))), upper=Decimal(str(round(max(yhat + hi, 0), 2))),
        )
    return {"status": "ok", "version": version.version, "selected": result["selected"]}


@transaction.atomic
def run_segmentation(business):
    df = segmentation.compute_rfm(business)
    if df is None:
        return {"status": "insufficient_data", "message": f"Need at least {segmentation.MIN_CUSTOMERS} customers with purchases."}
    labels, km_info = segmentation.run_kmeans(df)
    if labels is not None:
        df["cluster"] = labels
    version = _new_version(business, ModelVersion.Kind.SEGMENTS, "rfm_rules+kmeans" if km_info else "rfm_rules", n_samples=len(df),
                           metrics={"segment_counts": df["segment"].value_counts().to_dict(), "kmeans": km_info})
    valid_ids = set(Customer.objects.for_business(business).values_list("id", flat=True))
    CustomerSegment.objects.for_business(business).exclude(customer_id__in=df["customer_id"].tolist()).delete()
    for row in df.itertuples():
        if row.customer_id not in valid_ids:
            continue
        CustomerSegment.objects.update_or_create(
            business=business, customer_id=row.customer_id,
            defaults=dict(recency_days=int(row.recency), frequency=int(row.freq), monetary=Decimal(str(round(row.monetary, 2))),
                          r_score=int(row.R), f_score=int(row.F), m_score=int(row.M), segment=row.segment,
                          kmeans_cluster=int(row.cluster) if "cluster" in df.columns else None),
        )
    return {"status": "ok", "version": version.version, "customers": len(df)}


@transaction.atomic
def run_anomaly_detection(business):
    flagged, info = anomaly.detect(business)
    if flagged is None:
        return {"status": "insufficient_data", "message": f"Need at least {anomaly.MIN_SALES} completed sales."}
    version = _new_version(business, ModelVersion.Kind.ANOMALY, "isolation_forest", n_samples=info["n_sales"], metrics=info)
    keep = set(flagged["sale_id"].tolist())
    AnomalyFlag.objects.for_business(business).filter(reviewed=False).exclude(sale_id__in=keep).delete()
    for row in flagged.itertuples():
        AnomalyFlag.objects.update_or_create(
            business=business, sale_id=row.sale_id, defaults={"score": float(row.score), "reasons": row.reasons},
        )
    return {"status": "ok", "version": version.version, "flagged": info["n_flagged"]}


@transaction.atomic
def run_associations(business):
    rules, info = recommendations.compute_associations(business)
    if rules is None:
        return {"status": "insufficient_data", "message": f"Need at least {recommendations.MIN_BASKETS} completed sales."}
    version = _new_version(business, ModelVersion.Kind.ASSOC, "co-occurrence (support/confidence/lift)", n_samples=info["n_baskets"], metrics=info)
    ProductAssociation.objects.for_business(business).delete()
    ProductAssociation.objects.bulk_create([
        ProductAssociation(business=business, product_a_id=r["a"], product_b_id=r["b"], pair_count=r["count"],
                           support=r["support"], confidence=r["confidence"], lift=r["lift"]) for r in rules
    ])
    return {"status": "ok", "version": version.version, "rules": len(rules)}


def run_all(business):
    """Run every pipeline; one failure never blocks the others."""
    out = {}
    for name, fn in [("demand", run_demand_forecast), ("sales_forecast", run_sales_forecast), ("segments", run_segmentation),
                     ("anomalies", run_anomaly_detection), ("associations", run_associations)]:
        try:
            out[name] = fn(business)
        except Exception as exc:  # noqa: BLE001 - report and continue
            out[name] = {"status": "error", "message": f"{type(exc).__name__}: {exc}"}
    return out
