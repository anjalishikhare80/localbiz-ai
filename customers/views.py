from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import FormView, TemplateView

from businesses.permissions import has_perm
from core.exceptions import BusinessRuleError
from core.views import BusinessViewMixin, TenantCreateView, TenantListView, TenantUpdateView

from .forms import CustomerForm, CustomerPaymentForm
from .models import Customer
from .services import customers_with_stats, receive_customer_payment


class CustomerListView(TenantListView):
    model = Customer
    required_permission = "customers.view"
    title = "Customers"
    search_fields = ["name", "phone", "email"]
    create_url_name = "customers:add"
    create_permission = "customers.manage"
    edit_url_name = "customers:edit"
    edit_permission = "customers.manage"
    detail_url_name = "customers:detail"
    columns = [
        ("Name", "name"),
        ("Phone", "phone"),
        ("Orders", "order_count"),
        ("Total spent", "total_spent"),
        ("Outstanding", "outstanding"),
        ("Last purchase", "last_purchase"),
        ("Active", "is_active"),
    ]

    def get_queryset(self):
        qs = customers_with_stats(self.request.business)
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
        if self.request.GET.get("owing") == "1":
            qs = qs.filter(outstanding__gt=0)
        return qs


class CustomerCreateView(TenantCreateView):
    model = Customer
    form_class = CustomerForm
    required_permission = "customers.manage"
    title = "Add customer"
    success_url_name = "customers:list"


class CustomerUpdateView(TenantUpdateView):
    model = Customer
    form_class = CustomerForm
    required_permission = "customers.manage"
    title = "Edit customer"
    success_url_name = "customers:list"


class CustomerDetailView(BusinessViewMixin, TemplateView):
    required_permission = "customers.view"
    template_name = "customers/detail.html"

    def get_context_data(self, **kwargs):
        from ml.models import CustomerSegment
        from sales.models import Sale

        ctx = super().get_context_data(**kwargs)
        customer = get_object_or_404(customers_with_stats(self.request.business), pk=self.kwargs["pk"])
        ctx["customer"] = customer
        ctx["sales"] = Sale.objects.for_business(self.request.business).filter(customer=customer).select_related("invoice").order_by("-sale_date")[:25]
        ctx["segment"] = CustomerSegment.objects.for_business(self.request.business).filter(customer=customer).first()
        ctx["can_manage"] = has_perm(self.request.membership.role, "customers.manage")
        ctx["avg_order"] = (customer.total_spent / customer.order_count) if customer.order_count else 0
        return ctx


class CustomerPaymentView(BusinessViewMixin, FormView):
    required_permission = "customers.manage"
    form_class = CustomerPaymentForm
    template_name = "core/form.html"

    def get_customer(self):
        return get_object_or_404(customers_with_stats(self.request.business), pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.get_customer()
        ctx.update(title=f"Receive payment from {c.name}", subtitle=f"Outstanding: {c.outstanding:,.2f}",
                   cancel_url=reverse("customers:detail", args=[c.pk]))
        return ctx

    def form_valid(self, form):
        customer = self.get_customer()
        try:
            receive_customer_payment(business=self.request.business, user=self.request.user, customer=customer,
                                     amount=form.cleaned_data["amount"], method=form.cleaned_data["method"], request=self.request)
        except BusinessRuleError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Payment recorded.")
        return redirect("customers:detail", pk=customer.pk)
