from datetime import timedelta

import numpy as np
import pandas as pd
from django.test import TestCase
from django.utils import timezone

from core.testing import make_business, make_customer, make_product
from ml import anomaly, forecasting, recommendations, segmentation
from ml.models import AnomalyFlag, CustomerSegment, DemandForecast, ModelVersion, ProductAssociation, SalesForecast
from ml.services import run_all, run_anomaly_detection, run_associations, run_demand_forecast, run_segmentation
from sales.services import create_sale


def synthetic_series(days=200, groups=(1, 2), seed=0, weekly=(1.0, 1.0, 1.1, 1.0, 1.3, 2.0, 0.4), base=3):
    rng = np.random.default_rng(seed)
    end = pd.Timestamp(timezone.localdate() - timedelta(days=1))
    dates = pd.date_range(end - pd.Timedelta(days=days - 1), end)
    frames = []
    for g in groups:
        pattern = np.array(weekly)[dates.dayofweek]
        y = rng.poisson(base * g * pattern).astype(float)
        frames.append(pd.DataFrame({"group": g, "date": dates, "y": y}))
    return pd.concat(frames, ignore_index=True)


class FeatureLeakageTests(TestCase):
    def test_features_never_use_information_newer_than_the_horizon(self):
        df = synthetic_series(groups=(1,))
        H = 7
        f = forecasting.make_features(df, H).set_index("date")
        y = df.set_index("date")["y"]
        for d in f.index[40:60]:
            self.assertEqual(f.loc[d, f"lag_{H}"], y.loc[d - pd.Timedelta(days=H)])        # exactly H days old
            self.assertAlmostEqual(f.loc[d, "roll7"], y.loc[d - pd.Timedelta(days=H + 6): d - pd.Timedelta(days=H)].mean())
        # changing "future" values must not change today's features
        df2 = df.copy()
        df2.loc[df2["date"] > df["date"].iloc[100], "y"] = 9999
        f2 = forecasting.make_features(df2, H).set_index("date")
        d = df["date"].iloc[100] + pd.Timedelta(days=3)    # within H days of the changed region
        self.assertEqual(f.loc[d, f"lag_{H}"], f2.loc[d, f"lag_{H}"])

    def test_metrics_are_computed_correctly(self):
        m = forecasting._metrics([10, 0, 20], [8, 1, 22])
        self.assertAlmostEqual(m["mae"], (2 + 1 + 2) / 3, places=3)
        self.assertAlmostEqual(m["wape"], 5 / 30, places=3)


class ForecastingTests(TestCase):
    def test_returns_none_when_history_is_too_short(self):
        self.assertIsNone(forecasting.evaluate_and_forecast(synthetic_series(days=30), 7))

    def test_forecast_shape_metrics_and_selection(self):
        res = forecasting.evaluate_and_forecast(synthetic_series(days=220), 7)
        self.assertIsNotNone(res)
        self.assertEqual(set(res["metrics"]), {"seasonal_naive", "mean_28d", "group_mean", "dow_mean", "gradient_boosting"})
        self.assertEqual(res["selected_by"], "mae")
        best = min(m["mae"] for m in res["metrics"].values())
        self.assertEqual(res["metrics"][res["selected"]]["mae"], best)       # the chosen method really is the best on held-out data
        res2 = forecasting.evaluate_and_forecast(synthetic_series(days=220), 7, select_by="block_mae")
        self.assertEqual(res2["selected_by"], "block_mae")
        self.assertIn("block_wape", res2["metrics"][res2["selected"]])
        best_block = min(m["block_mae"] for m in res2["metrics"].values())
        self.assertEqual(res2["metrics"][res2["selected"]]["block_mae"], best_block)
        fc = res["forecast"]
        self.assertEqual(len(fc), 7 * 2)                        # 7 days for each of 2 series
        self.assertTrue((fc["yhat"] >= 0).all())
        self.assertEqual(fc["date"].min().date(), timezone.localdate())  # starts today (last data day = yesterday)

    def test_learned_model_beats_global_mean_on_weekly_pattern(self):
        strong = synthetic_series(days=300, groups=(1, 2), weekly=(0.3, 0.5, 1.0, 1.0, 2.0, 4.0, 0.2), base=5)
        res = forecasting.evaluate_and_forecast(strong, 7)
        # with a strong weekly pattern the learned model must clearly beat a plain average...
        self.assertLess(res["metrics"]["gradient_boosting"]["mae"], 0.8 * res["metrics"]["group_mean"]["mae"])
        # ...and the system must therefore not pick the plain average
        self.assertNotEqual(res["selected"], "group_mean")


class SegmentationTests(TestCase):
    def test_segment_rules(self):
        self.assertEqual(segmentation.label_segment(200, 1, 5, 5), "Inactive")
        self.assertEqual(segmentation.label_segment(40, 2, 4, 3), "At Risk")
        self.assertEqual(segmentation.label_segment(5, 5, 5, 5), "High Value")
        self.assertEqual(segmentation.label_segment(5, 4, 4, 2), "Loyal")
        self.assertEqual(segmentation.label_segment(10, 3, 1, 1), "Occasional")

    def test_rfm_scores_orientation(self):
        business, owner = make_business()
        p = make_product(business, stock=10000, price="100")
        now = timezone.now()
        # customer i buys i+1 times, more recently for larger i
        for i in range(12):
            c = make_customer(business, f"C{i}")
            for k in range(i + 1):
                create_sale(business=business, user=owner, customer=c, items=[{"product_id": p.id, "quantity": 1}],
                            sale_date=now - timedelta(days=(12 - i) * 5 + k))
        df = segmentation.compute_rfm(business)
        top = df.sort_values("freq").iloc[-1]
        bottom = df.sort_values("freq").iloc[0]
        self.assertGreater(top["F"], bottom["F"])
        self.assertGreater(top["R"], bottom["R"])        # more recent customer -> higher recency score
        self.assertGreater(top["M"], bottom["M"])
        result = run_segmentation(business)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(CustomerSegment.objects.for_business(business).count(), 12)

    def test_too_few_customers_is_reported_not_faked(self):
        business, owner = make_business()
        self.assertEqual(run_segmentation(business)["status"], "insufficient_data")


class AssociationTests(TestCase):
    def test_support_confidence_lift(self):
        business, owner = make_business()
        a = make_product(business, "Printer", stock=1000)
        b = make_product(business, "Ink", stock=1000)
        c = make_product(business, "Pen", stock=1000)
        for _ in range(10):   # printer + ink together
            create_sale(business=business, user=owner, items=[{"product_id": a.id, "quantity": 1}, {"product_id": b.id, "quantity": 1}])
        for _ in range(10):
            create_sale(business=business, user=owner, items=[{"product_id": a.id, "quantity": 1}])
        for _ in range(20):
            create_sale(business=business, user=owner, items=[{"product_id": c.id, "quantity": 1}])
        rules, info = recommendations.compute_associations(business)
        self.assertEqual(info["n_baskets"], 40)
        r = next(x for x in rules if x["a"] == a.id and x["b"] == b.id)
        self.assertAlmostEqual(r["confidence"], 10 / 20)       # half of printer baskets contain ink
        self.assertAlmostEqual(r["support"], 10 / 40)
        self.assertAlmostEqual(r["lift"], (10 / 20) / (10 / 40))  # 2.0
        run_associations(business)
        self.assertTrue(ProductAssociation.objects.for_business(business).filter(product_a=a, product_b=b).exists())

    def test_not_enough_baskets(self):
        business, owner = make_business()
        self.assertEqual(run_associations(business)["status"], "insufficient_data")


class AnomalyTests(TestCase):
    def test_injected_outlier_is_flagged_with_a_reason_and_label(self):
        business, owner = make_business()
        p = make_product(business, "Pen", stock=100000, price="10")
        q = make_product(business, "Book", stock=100000, price="50")
        now = timezone.now().replace(hour=12)
        rng = np.random.default_rng(1)
        for i in range(150):
            items = [{"product_id": p.id, "quantity": int(rng.integers(1, 4))}]
            if i % 3 == 0:
                items.append({"product_id": q.id, "quantity": 1})
            create_sale(business=business, user=owner, items=items, sale_date=now - timedelta(days=int(rng.integers(1, 60))))
        odd = create_sale(business=business, user=owner, items=[{"product_id": p.id, "quantity": 500}], sale_date=now - timedelta(days=2))
        result = run_anomaly_detection(business)
        self.assertEqual(result["status"], "ok")
        flag = AnomalyFlag.objects.for_business(business).get(sale=odd)
        self.assertTrue(flag.reasons)
        from api.serializers import AnomalySerializer
        self.assertEqual(AnomalySerializer(flag).data["label"], "Potentially unusual transaction")

    def test_needs_minimum_data(self):
        business, owner = make_business()
        self.assertEqual(run_anomaly_detection(business)["status"], "insufficient_data")


class PipelineTests(TestCase):
    def test_empty_business_reports_insufficient_data_everywhere_without_crashing(self):
        business, owner = make_business()
        out = run_all(business)
        self.assertEqual({v["status"] for v in out.values()}, {"insufficient_data"})
        self.assertFalse(ModelVersion.objects.for_business(business).exists())

    def test_demand_forecast_pipeline_versions_and_status(self):
        business, owner = make_business()
        fast = make_product(business, "Fast", stock=100000, price="10")
        slow = make_product(business, "Slow", stock=100000, price="10")
        now = timezone.now().replace(hour=12)
        rng = np.random.default_rng(3)
        for d in range(1, 150):
            when = now - timedelta(days=d)
            for _ in range(int(rng.poisson(3))):
                create_sale(business=business, user=owner, items=[{"product_id": fast.id, "quantity": 2}], sale_date=when, log_audit=False)
            if d % 25 == 0:
                create_sale(business=business, user=owner, items=[{"product_id": slow.id, "quantity": 1}], sale_date=when, log_audit=False)
        r1 = run_demand_forecast(business)
        self.assertEqual(r1["status"], "ok")
        r2 = run_demand_forecast(business)
        self.assertEqual(r2["version"], r1["version"] + 1)
        self.assertEqual(ModelVersion.objects.for_business(business).filter(kind="DEMAND", is_active=True).count(), 1)
        f_fast = DemandForecast.objects.for_business(business, ).get(product=fast, model_version__is_active=True)
        f_slow = DemandForecast.objects.for_business(business).get(product=slow, model_version__is_active=True)
        self.assertEqual(f_fast.status, "SUFFICIENT")
        self.assertGreater(f_fast.predicted_demand, 0)
        self.assertEqual(f_slow.status, "INSUFFICIENT_DATA")        # too few sale days: no fake prediction
        # shortage logic
        from catalog.models import Product
        Product.objects.filter(pk=fast.pk).update(current_stock=1)
        r3 = run_demand_forecast(business)
        f = DemandForecast.objects.for_business(business).get(product=fast, model_version__is_active=True)
        self.assertEqual(f.status, "SHORTAGE_RISK")
        self.assertGreater(f.suggested_reorder, 0)
