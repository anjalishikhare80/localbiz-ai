import json

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import FormView, TemplateView

from catalog.models import Supplier
from core.exceptions import BusinessRuleError
from core.views import BusinessViewMixin, TenantListView

from .forms import StockAdjustForm, SupplierPaymentForm
from .models import Purchase, StockTransaction
from .services import manual_adjustment, pay_supplier, receive_purchase


class StockLedgerView(TenantListView):
    model = StockTransaction
    required_permission = "inventory.view"
    title = "Stock ledger"
    search_fields = ["product__name", "product__sku", "note"]
    paginate_by = 30
    create_url_name = "inventory:adjust"
    create_label = "Adjust stock"
    create_permission = "inventory.manage"
    columns = [
        ("When", "occurred_at"),
        ("Product", "product.name"),
        ("Type", "get_txn_type_display"),
        ("Change", lambda o: f"{o.quantity_change:+d}"),
        ("Stock after", "stock_after"),
        ("Reference", lambda o: f"{o.reference_type} #{o.reference_id}" if o.reference_type and o.reference_id else o.reference_type),
        ("By", "created_by.username"),
        ("Note", "note"),
    ]

    def filter_queryset(self, qs):
        qs = qs.select_related("product", "created_by")
        if self.request.GET.get("product"):
            qs = qs.filter(product_id=self.request.GET["product"])
        return qs


class StockAdjustView(BusinessViewMixin, FormView):
    required_permission = "inventory.manage"
    form_class = StockAdjustForm
    template_name = "core/form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["business"] = self.request.business
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(title="Adjust stock", cancel_url=reverse("inventory:ledger"))
        return ctx

    def form_valid(self, form):
        d = form.cleaned_data
        try:
            manual_adjustment(
                business=self.request.business, user=self.request.user, product=d["product"],
                txn_type=d["txn_type"], quantity=d["quantity"], note=d["note"], request=self.request,
            )
        except BusinessRuleError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Stock updated.")
        return redirect("inventory:ledger")


class PurchaseListView(TenantListView):
    model = Purchase
    required_permission = "inventory.manage"
    title = "Purchases (stock in)"
    search_fields = ["supplier__name", "note"]
    create_url_name = "inventory:purchase_add"
    create_label = "Record purchase"
    create_permission = "inventory.manage"
    extra_actions = [("Pay supplier", "inventory:purchase_pay", "inventory.manage")]
    columns = [
        ("#", "id"),
        ("Date", "purchase_date"),
        ("Supplier", "supplier.name"),
        ("Items", lambda o: o.items.count()),
        ("Total", "total_amount"),
        ("Paid", "paid_amount"),
        ("Balance", lambda o: o.total_amount - o.paid_amount),
    ]

    def filter_queryset(self, qs):
        return qs.select_related("supplier")


class PurchaseCreateView(BusinessViewMixin, TemplateView):
    """Cart-style entry screen; the cart is posted as JSON to this same URL."""

    required_permission = "inventory.manage"
    template_name = "inventory/purchase_new.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["suppliers"] = Supplier.objects.for_business(self.request.business).filter(is_active=True)
        return ctx

    def post(self, request, *args, **kwargs):
        try:
            payload = json.loads(request.body)
            supplier = get_object_or_404(Supplier.objects.for_business(request.business), pk=payload.get("supplier_id"))
            with transaction.atomic():
                purchase = receive_purchase(
                    business=request.business, user=request.user, supplier=supplier,
                    items=payload.get("items", []), paid_amount=payload.get("paid_amount") or 0,
                    note=payload.get("note", ""), request=request,
                )
        except BusinessRuleError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return JsonResponse({"ok": False, "error": "Invalid data submitted."}, status=400)
        return JsonResponse({"ok": True, "redirect": reverse("inventory:purchase_list"), "id": purchase.pk})


class PurchasePayView(BusinessViewMixin, FormView):
    required_permission = "inventory.manage"
    form_class = SupplierPaymentForm
    template_name = "core/form.html"

    def get_purchase(self):
        return get_object_or_404(Purchase.objects.for_business(self.request.business), pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        purchase = self.get_purchase()
        ctx.update(title="Pay supplier", subtitle=f"Purchase #{purchase.pk} - outstanding {purchase.balance:,.2f}",
                   cancel_url=reverse("inventory:purchase_list"))
        return ctx

    def form_valid(self, form):
        self.get_purchase()
        try:
            pay_supplier(business=self.request.business, user=self.request.user, purchase_id=self.kwargs["pk"],
                         amount=form.cleaned_data["amount"], request=self.request)
        except BusinessRuleError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Payment recorded.")
        return redirect("inventory:purchase_list")
