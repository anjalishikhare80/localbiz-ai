from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView

from audit.services import log as audit_log
from core.views import BusinessViewMixin

from .models import AnomalyFlag, CustomerSegment, DemandForecast, ModelVersion, ProductAssociation, SalesForecast
from .services import run_all


class MLOverviewView(BusinessViewMixin, TemplateView):
    required_permission = "ml.view"
    template_name = "ml/overview.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        b = self.request.business

        def active(kind):
            return ModelVersion.objects.for_business(b).filter(kind=kind, is_active=True).first()

        dv, sv, gv, av, xv = (active(k) for k in ("DEMAND", "SALES", "SEGMENTS", "ANOMALY", "ASSOC"))
        ctx.update(demand_version=dv, sales_version=sv, segment_version=gv, anomaly_version=av, assoc_version=xv)
        ctx["demand"] = list(DemandForecast.objects.for_business(b).filter(model_version=dv).select_related("product").order_by("status", "-predicted_demand")[:60]) if dv else []
        ctx["sales_forecast"] = list(SalesForecast.objects.for_business(b).filter(model_version=sv)) if sv else []
        ctx["sf_labels"] = [f.forecast_date.strftime("%d %b") for f in ctx["sales_forecast"]]
        ctx["sf_pred"] = [float(f.predicted_amount) for f in ctx["sales_forecast"]]
        ctx["sf_lo"] = [float(f.lower) for f in ctx["sales_forecast"]]
        ctx["sf_hi"] = [float(f.upper) for f in ctx["sales_forecast"]]
        ctx["segments"] = list(CustomerSegment.objects.for_business(b).select_related("customer").order_by("segment", "-monetary")[:80])
        ctx["segment_counts"] = (gv.metrics.get("segment_counts", {}) if gv else {})
        ctx["kmeans"] = (gv.metrics.get("kmeans") if gv else None)
        ctx["anomalies"] = list(AnomalyFlag.objects.for_business(b).select_related("sale", "sale__invoice").order_by("-score")[:30])
        ctx["associations"] = list(ProductAssociation.objects.for_business(b).select_related("product_a", "product_b").order_by("-lift")[:25])
        return ctx


class TrainView(BusinessViewMixin, View):
    required_permission = "ml.train"

    def post(self, request):
        results = run_all(request.business)
        audit_log(business=request.business, user=request.user, action="ml.retrained",
                  metadata={k: v.get("status") for k, v in results.items()}, request=request)
        ok = [k for k, v in results.items() if v.get("status") == "ok"]
        skipped = [k for k, v in results.items() if v.get("status") == "insufficient_data"]
        errors = [k for k, v in results.items() if v.get("status") == "error"]
        if ok:
            messages.success(request, "Trained: " + ", ".join(ok))
        if skipped:
            messages.warning(request, "Not enough data for: " + ", ".join(skipped))
        if errors:
            messages.error(request, "Failed: " + ", ".join(errors))
        return redirect("ml:overview")


class MarkReviewedView(BusinessViewMixin, View):
    required_permission = "ml.view"

    def post(self, request, pk):
        AnomalyFlag.objects.for_business(request.business).filter(pk=pk).update(reviewed=True)
        return redirect("ml:overview")


class RecommendView(BusinessViewMixin, View):
    """JSON: products frequently bought with the given product (used on the sale screen)."""

    required_permission = "products.view"

    def get(self, request, product_id):
        rows = (ProductAssociation.objects.for_business(request.business).filter(product_a_id=product_id, product_b__is_active=True)
                .select_related("product_b").order_by("-lift")[:3])
        return JsonResponse({"results": [{"id": r.product_b_id, "name": r.product_b.name, "confidence": round(r.confidence * 100), "lift": round(r.lift, 1)} for r in rows]})
