from datetime import date, timedelta

from django.db.models import F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from analytics import services as analytics_services
from analytics.insights import generate_insights
from analytics.reports import REPORTS
from businesses.models import BusinessMember
from catalog.models import Category, Product, Supplier
from core.exceptions import BusinessRuleError
from customers.models import Customer
from customers.services import customers_with_stats, receive_customer_payment
from finance.models import Expense, ExpenseCategory
from inventory.models import Purchase, StockTransaction
from inventory.services import manual_adjustment, receive_purchase
from ml.models import AnomalyFlag, CustomerSegment, DemandForecast, ProductAssociation, SalesForecast
from ml.services import run_all
from sales.models import Sale
from sales.services import cancel_sale, create_sale, record_payment

from . import serializers as s
from .base import ScopedQuerysetMixin, TenantAPIMixin


class LoginThrottledTokenView(TokenObtainPairView):
    """POST username + password -> access & refresh JWT. Rate limited (10/min)."""

    throttle_scope = "login"
    throttle_classes = [ScopedRateThrottle]


class MeView(TenantAPIMixin, APIView):
    perm_view = None

    def get(self, request):
        memberships = BusinessMember.objects.filter(user=request.user, is_active=True).select_related("business")
        return Response({
            "username": request.user.username, "email": request.user.email,
            "active_business": {"id": request.business.id, "name": request.business.name, "role": request.membership.role},
            "memberships": [{"business_id": m.business_id, "business": m.business.name, "role": m.role} for m in memberships],
        })


class BaseViewSet(ScopedQuerysetMixin, viewsets.ModelViewSet):
    filter_backends = [SearchFilter, OrderingFilter]


class CategoryViewSet(BaseViewSet):
    model = Category
    serializer_class = s.CategorySerializer
    perm_view, perm_manage = "products.view", "products.manage"
    search_fields = ["name"]
    ordering_fields = ["name"]


class SupplierViewSet(BaseViewSet):
    model = Supplier
    serializer_class = s.SupplierSerializer
    perm_view = perm_manage = "suppliers.manage"
    search_fields = ["name", "contact_person", "phone"]
    ordering_fields = ["name"]


class ProductViewSet(BaseViewSet):
    model = Product
    serializer_class = s.ProductSerializer
    perm_view, perm_manage = "products.view", "products.manage"
    search_fields = ["name", "sku", "barcode"]
    ordering_fields = ["name", "selling_price", "current_stock"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("category", "supplier")
        p = self.request.query_params
        if p.get("is_active") in ("true", "false"):
            qs = qs.filter(is_active=p["is_active"] == "true")
        if p.get("low_stock") == "true":
            qs = qs.filter(is_active=True, current_stock__lte=F("reorder_level"))
        if p.get("category"):
            qs = qs.filter(category_id=p["category"])
        return qs

    def destroy(self, request, *args, **kwargs):
        # Soft delete: sales history must remain intact.
        product = self.get_object()
        product.is_active = False
        product.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class StockTransactionViewSet(ScopedQuerysetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    model = StockTransaction
    serializer_class = s.StockTransactionSerializer
    perm_view = "inventory.view"
    perm_by_action = {"adjust": "inventory.manage"}
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["product__name", "note"]
    ordering_fields = ["occurred_at"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("product", "created_by")
        if self.request.query_params.get("product"):
            qs = qs.filter(product_id=self.request.query_params["product"])
        return qs

    @action(detail=False, methods=["post"])
    def adjust(self, request):
        ser = s.StockAdjustSerializer(data=request.data, context=self.get_serializer_context())
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        txn = manual_adjustment(business=request.business, user=request.user, product=d["product"],
                                txn_type=d["txn_type"], quantity=d["quantity"], note=d["note"], request=request)
        return Response(s.StockTransactionSerializer(txn).data, status=status.HTTP_201_CREATED)


class CustomerViewSet(BaseViewSet):
    model = Customer
    serializer_class = s.CustomerSerializer
    perm_view, perm_manage = "customers.view", "customers.manage"
    perm_by_action = {"receive_payment": "customers.manage"}
    search_fields = ["name", "phone", "email"]
    ordering_fields = ["name"]

    def get_queryset(self):
        return customers_with_stats(self.request.business)

    @action(detail=True, methods=["post"], url_path="receive-payment")
    def receive_payment(self, request, pk=None):
        customer = self.get_object()
        ser = s.PaymentInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        receive_customer_payment(business=request.business, user=request.user, customer=customer,
                                 amount=ser.validated_data["amount"], method=ser.validated_data["method"], request=request)
        return Response(s.CustomerSerializer(self.get_queryset().get(pk=customer.pk)).data)


class SaleViewSet(ScopedQuerysetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    model = Sale
    serializer_class = s.SaleSerializer
    perm_view, perm_manage = "sales.view", "sales.create"
    perm_by_action = {"cancel": "sales.cancel", "payments": "customers.manage"}
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["invoice__number", "customer__name"]
    ordering_fields = ["sale_date", "total"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("customer", "invoice").prefetch_related("items")
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"].upper())
        if p.get("customer"):
            qs = qs.filter(customer_id=p["customer"])
        for key, lookup in (("date_from", "sale_date__date__gte"), ("date_to", "sale_date__date__lte")):
            if p.get(key):
                try:
                    qs = qs.filter(**{lookup: date.fromisoformat(p[key])})
                except ValueError:
                    pass
        return qs

    def create(self, request, *args, **kwargs):
        ser = s.SaleCreateSerializer(data=request.data, context=self.get_serializer_context())
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        sale = create_sale(
            business=request.business, user=request.user, customer=d.get("customer"),
            items=[{"product_id": i["product"].id, "quantity": i["quantity"], "discount": i["discount"]} for i in d["items"]],
            payment_method=d["payment_method"], amount_paid=d.get("amount_paid"), note=d["note"], request=request,
        )
        sale = self.get_queryset().get(pk=sale.pk)
        return Response(s.SaleSerializer(sale).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        sale = self.get_object()
        cancel_sale(business=request.business, user=request.user, sale_id=sale.pk, request=request)
        return Response(s.SaleSerializer(self.get_queryset().get(pk=sale.pk)).data)

    @action(detail=True, methods=["post"])
    def payments(self, request, pk=None):
        sale = self.get_object()
        ser = s.PaymentInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        record_payment(business=request.business, user=request.user, sale_id=sale.pk, amount=ser.validated_data["amount"],
                       method=ser.validated_data["method"], note=ser.validated_data["note"], request=request)
        return Response(s.SaleSerializer(self.get_queryset().get(pk=sale.pk)).data)


class PurchaseViewSet(ScopedQuerysetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    model = Purchase
    serializer_class = s.PurchaseSerializer
    perm_view = perm_manage = "inventory.manage"

    def get_queryset(self):
        return super().get_queryset().select_related("supplier")

    def create(self, request, *args, **kwargs):
        ser = s.PurchaseCreateSerializer(data=request.data, context=self.get_serializer_context())
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        purchase = receive_purchase(
            business=request.business, user=request.user, supplier=d["supplier"], paid_amount=d["paid_amount"], note=d["note"],
            items=[{"product_id": i["product"].id, "quantity": i["quantity"], "unit_cost": i["unit_cost"]} for i in d["items"]],
            request=request,
        )
        return Response(s.PurchaseSerializer(purchase).data, status=status.HTTP_201_CREATED)


class ExpenseCategoryViewSet(BaseViewSet):
    model = ExpenseCategory
    serializer_class = s.ExpenseCategorySerializer
    perm_view = perm_manage = "expenses.manage"


class ExpenseViewSet(BaseViewSet):
    model = Expense
    serializer_class = s.ExpenseSerializer
    perm_view = perm_manage = "expenses.manage"
    search_fields = ["description", "category__name"]
    ordering_fields = ["expense_date", "amount"]

    def get_queryset(self):
        return super().get_queryset().select_related("category")

    def perform_create(self, serializer):
        serializer.save(business=self.request.business, created_by=self.request.user)


# ---------------- analytics / reports / ML ----------------
class KPIView(TenantAPIMixin, APIView):
    perm_view = "analytics.sales"

    def get(self, request):
        k = analytics_services.kpis(request.business, financial=self.can("analytics.financial"))
        out = {key: (str(v) if not isinstance(v, (int, bool)) else v) for key, v in k.items()
               if key not in ("low_stock", "top_products", "recent_sales")}
        out["low_stock"] = [{"id": p.id, "name": p.name, "stock": p.current_stock, "reorder_level": p.reorder_level} for p in k["low_stock"]]
        out["top_products"] = [{"product": r["product_name"], "quantity": r["qty"], "revenue": str(r["revenue"])} for r in k["top_products"]]
        return Response(out)


class InsightsView(TenantAPIMixin, APIView):
    perm_view = "analytics.sales"

    def get(self, request):
        return Response({"insights": generate_insights(request.business)})


class ReportView(TenantAPIMixin, APIView):
    perm_view = "reports.view"

    def get(self, request, slug):
        if slug not in REPORTS:
            raise Http404
        title, builder, perm, _ = REPORTS[slug]
        if not self.can(perm):
            return Response({"error": {"status": 403, "message": "You do not have permission to perform this action.", "details": None}}, status=403)
        today = timezone.localdate()

        def _d(key, default):
            try:
                return date.fromisoformat(request.query_params.get(key, ""))
            except ValueError:
                return default

        headers, rows = builder(request.business, _d("start", today - timedelta(days=29)), _d("end", today))
        return Response({"report": title, "headers": headers, "rows": [[str(c) if c is not None else None for c in r] for r in rows]})


class DemandForecastView(TenantAPIMixin, APIView):
    perm_view = "ml.view"

    def get(self, request):
        qs = DemandForecast.objects.for_business(request.business).filter(model_version__is_active=True).select_related("product", "model_version")
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"].upper())
        return Response(s.DemandForecastSerializer(qs, many=True).data)


class SalesForecastView(TenantAPIMixin, APIView):
    perm_view = "ml.view"

    def get(self, request):
        qs = SalesForecast.objects.for_business(request.business).filter(model_version__is_active=True)
        return Response(s.SalesForecastSerializer(qs, many=True).data)


class SegmentsView(TenantAPIMixin, APIView):
    perm_view = "ml.view"

    def get(self, request):
        qs = CustomerSegment.objects.for_business(request.business).select_related("customer")
        return Response(s.CustomerSegmentSerializer(qs, many=True).data)


class AnomaliesView(TenantAPIMixin, APIView):
    perm_view = "ml.view"

    def get(self, request):
        qs = AnomalyFlag.objects.for_business(request.business).select_related("sale", "sale__invoice")
        return Response(s.AnomalySerializer(qs, many=True).data)


class RecommendationsView(TenantAPIMixin, APIView):
    perm_view = "products.view"

    def get(self, request):
        qs = ProductAssociation.objects.for_business(request.business).select_related("product_a", "product_b")
        if request.query_params.get("product"):
            qs = qs.filter(product_a_id=request.query_params["product"])
        return Response(s.AssociationSerializer(qs[:50], many=True).data)


class TrainView(TenantAPIMixin, APIView):
    perm_view = perm_manage = "ml.train"

    def post(self, request):
        return Response(run_all(request.business))
