import json

from django.contrib import messages
from django.db.models import F, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import FormView, TemplateView

from audit.services import log as audit_log
from businesses.permissions import has_perm
from core.exceptions import BusinessRuleError
from core.views import BusinessViewMixin, TenantListView
from customers.models import Customer

from .forms import PaymentForm
from .models import Sale
from .pdf import build_invoice_pdf
from .services import cancel_sale, create_sale, record_payment


class SaleListView(TenantListView):
    model = Sale
    required_permission = "sales.view"
    title = "Sales"
    create_url_name = "sales:new"
    create_label = "New sale"
    create_permission = "sales.create"
    detail_url_name = "sales:detail"
    paginate_by = 25
    columns = [
        ("Invoice", "invoice_number"),
        ("Date", "sale_date"),
        ("Customer", lambda o: o.customer.name if o.customer else "Walk-in"),
        ("Total", "total"),
        ("Paid", "amount_paid"),
        ("Status", "payment_status"),
    ]

    def get_queryset(self):
        qs = Sale.objects.for_business(self.request.business).select_related("customer", "invoice")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(invoice__number__icontains=q) | Q(customer__name__icontains=q))
        if self.request.GET.get("unpaid") == "1":
            qs = qs.filter(status="COMPLETED").exclude(amount_paid__gte=F("total"))
        return qs

    search_fields = ["invoice__number", "customer__name"]  # shows the search box; filtering is in get_queryset


class SaleCreateView(BusinessViewMixin, TemplateView):
    """Point-of-sale screen. The cart is submitted as JSON to this same URL."""

    required_permission = "sales.create"
    template_name = "sales/new.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["customers"] = Customer.objects.for_business(self.request.business).filter(is_active=True)
        ctx["tax_rate"] = self.request.business.tax_rate
        ctx["methods"] = Sale.Method.choices
        return ctx

    def post(self, request, *args, **kwargs):
        try:
            payload = json.loads(request.body)
            customer = None
            if payload.get("customer_id"):
                customer = get_object_or_404(Customer.objects.for_business(request.business), pk=payload["customer_id"])
            paid = payload.get("amount_paid")
            sale = create_sale(
                business=request.business, user=request.user, items=payload.get("items", []), customer=customer,
                payment_method=payload.get("payment_method", "CASH"),
                amount_paid=None if paid in (None, "") else paid, note=payload.get("note", ""), request=request,
            )
        except BusinessRuleError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return JsonResponse({"ok": False, "error": "Invalid data submitted."}, status=400)
        return JsonResponse({"ok": True, "redirect": reverse("sales:detail", args=[sale.pk])})


class SaleDetailView(BusinessViewMixin, TemplateView):
    required_permission = "sales.view"
    template_name = "sales/detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sale = get_object_or_404(
            Sale.objects.for_business(self.request.business).select_related("customer", "invoice", "created_by"),
            pk=self.kwargs["pk"],
        )
        role = self.request.membership.role
        ctx.update(
            sale=sale,
            items=sale.items.all(),
            payments=sale.payments.all(),
            can_cancel=has_perm(role, "sales.cancel") and sale.status == "COMPLETED",
            can_pay=has_perm(role, "customers.manage") and sale.status == "COMPLETED" and sale.balance > 0,
        )
        return ctx


class SaleCancelView(BusinessViewMixin, View):
    required_permission = "sales.cancel"

    def post(self, request, pk):
        try:
            cancel_sale(business=request.business, user=request.user, sale_id=pk, request=request)
            messages.success(request, "Sale cancelled and stock restored.")
        except BusinessRuleError as exc:
            messages.error(request, str(exc))
        return redirect("sales:detail", pk=pk)


class SalePaymentView(BusinessViewMixin, FormView):
    required_permission = "customers.manage"
    form_class = PaymentForm
    template_name = "core/form.html"

    def get_sale(self):
        return get_object_or_404(Sale.objects.for_business(self.request.business), pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sale = self.get_sale()
        ctx.update(title="Record payment", subtitle=f"{sale.invoice_number} - balance due {sale.balance:,.2f}",
                   cancel_url=reverse("sales:detail", args=[sale.pk]))
        return ctx

    def form_valid(self, form):
        self.get_sale()  # 404 for another business's sale
        try:
            record_payment(business=self.request.business, user=self.request.user, sale_id=self.kwargs["pk"],
                           amount=form.cleaned_data["amount"], method=form.cleaned_data["method"],
                           note=form.cleaned_data["note"], request=self.request)
        except BusinessRuleError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Payment recorded.")
        return redirect("sales:detail", pk=self.kwargs["pk"])


class InvoicePDFView(BusinessViewMixin, View):
    required_permission = "sales.view"

    def get(self, request, pk):
        sale = get_object_or_404(
            Sale.objects.for_business(request.business).select_related("business", "customer", "invoice"), pk=pk
        )
        pdf = build_invoice_pdf(sale)
        audit_log(business=request.business, user=request.user, action="invoice.generated", entity=sale,
                  metadata={"invoice": sale.invoice_number}, request=request)
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{sale.invoice_number}.pdf"'
        return response
