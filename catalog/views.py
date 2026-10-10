from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import TemplateView

from businesses.permissions import has_perm
from core.views import BusinessViewMixin, TenantCreateView, TenantListView, TenantUpdateView
from inventory.models import StockTransaction
from inventory.services import adjust_stock

from .forms import CategoryForm, ProductForm, SupplierForm
from .models import Category, Product, Supplier


# ---- Categories ----
class CategoryListView(TenantListView):
    model = Category
    required_permission = "products.view"
    title = "Categories"
    search_fields = ["name"]
    columns = [("Name", "name"), ("Products", lambda o: o.products.count())]
    create_url_name = "catalog:category_add"
    create_permission = "products.manage"
    edit_url_name = "catalog:category_edit"
    edit_permission = "products.manage"


class CategoryCreateView(TenantCreateView):
    model = Category
    form_class = CategoryForm
    required_permission = "products.manage"
    title = "Add category"
    success_url_name = "catalog:category_list"


class CategoryUpdateView(TenantUpdateView):
    model = Category
    form_class = CategoryForm
    required_permission = "products.manage"
    title = "Edit category"
    success_url_name = "catalog:category_list"


# ---- Suppliers ----
class SupplierListView(TenantListView):
    model = Supplier
    required_permission = "suppliers.manage"
    title = "Suppliers"
    search_fields = ["name", "contact_person", "phone"]
    create_url_name = "catalog:supplier_add"
    create_permission = "suppliers.manage"
    edit_url_name = "catalog:supplier_edit"
    edit_permission = "suppliers.manage"
    columns = [
        ("Name", "name"),
        ("Contact", "contact_person"),
        ("Phone", "phone"),
        ("Products", lambda o: o.products.count()),
        ("Purchases", lambda o: o.purchase_count),
        ("Total purchased", lambda o: o.purchase_total),
        ("Outstanding", lambda o: o.purchase_total - o.paid_total),
        ("Active", "is_active"),
    ]

    def get_queryset(self):
        from django.db.models import Count, DecimalField, Sum, Value
        from django.db.models.functions import Coalesce

        zero = Value(0, output_field=DecimalField())
        return super().get_queryset().annotate(
            purchase_count=Count("purchases", distinct=True),
            purchase_total=Coalesce(Sum("purchases__total_amount"), zero),
            paid_total=Coalesce(Sum("purchases__paid_amount"), zero),
        ).order_by("name")


class SupplierCreateView(TenantCreateView):
    model = Supplier
    form_class = SupplierForm
    required_permission = "suppliers.manage"
    title = "Add supplier"
    success_url_name = "catalog:supplier_list"


class SupplierUpdateView(TenantUpdateView):
    model = Supplier
    form_class = SupplierForm
    required_permission = "suppliers.manage"
    title = "Edit supplier"
    success_url_name = "catalog:supplier_list"


# ---- Products ----
class ProductListView(TenantListView):
    model = Product
    required_permission = "products.view"
    title = "Products"
    search_fields = ["name", "sku", "barcode"]
    create_url_name = "catalog:product_add"
    create_permission = "products.manage"
    edit_url_name = "catalog:product_edit"
    edit_permission = "products.manage"
    detail_url_name = "catalog:product_detail"

    def get_columns(self):
        cols = [("Name", "name"), ("SKU", "sku"), ("Category", "category.name"), ("Price", "selling_price"), ("Stock", "current_stock")]
        if has_perm(self.request.membership.role, "products.manage"):
            cols.insert(3, ("Cost", "purchase_price"))
            cols.append(("Reorder at", "reorder_level"))
        cols.append(("Status", lambda o: "Low stock" if o.is_low_stock and o.is_active else ("Inactive" if not o.is_active else "OK")))
        return cols

    def filter_queryset(self, qs):
        qs = qs.select_related("category")
        if self.request.GET.get("low") == "1":
            qs = qs.filter(is_active=True, current_stock__lte=F("reorder_level"))
        if self.request.GET.get("inactive") != "1":
            qs = qs.filter(is_active=True)
        return qs


class ProductCreateView(TenantCreateView):
    model = Product
    form_class = ProductForm
    required_permission = "products.manage"
    title = "Add product"
    success_url_name = "catalog:product_list"

    def after_save(self, obj, form, created):
        opening = form.cleaned_data.get("opening_stock") or 0
        if created and opening > 0:
            adjust_stock(
                business=self.request.business, product=obj, quantity_change=opening,
                txn_type=StockTransaction.TxnType.OPENING, user=self.request.user, note="Opening stock",
            )


class ProductUpdateView(TenantUpdateView):
    model = Product
    form_class = ProductForm
    required_permission = "products.manage"
    title = "Edit product"
    success_url_name = "catalog:product_list"


class ProductDetailView(BusinessViewMixin, TemplateView):
    required_permission = "products.view"
    template_name = "catalog/product_detail.html"

    def get_context_data(self, **kwargs):
        from ml.models import DemandForecast, ProductAssociation

        ctx = super().get_context_data(**kwargs)
        business = self.request.business
        product = get_object_or_404(Product.objects.for_business(business), pk=self.kwargs["pk"])
        can_manage = has_perm(self.request.membership.role, "products.manage")
        ctx["product"] = product
        ctx["can_manage"] = can_manage
        if has_perm(self.request.membership.role, "inventory.view"):
            ctx["ledger"] = StockTransaction.objects.for_business(business).filter(product=product).select_related("created_by")[:15]
        ctx["associations"] = (
            ProductAssociation.objects.for_business(business).filter(product_a=product).select_related("product_b").order_by("-lift")[:5]
        )
        if has_perm(self.request.membership.role, "ml.view"):
            ctx["forecast"] = (
                DemandForecast.objects.for_business(business).filter(product=product, model_version__is_active=True).first()
            )
        return ctx


class ProductSearchView(BusinessViewMixin, View):
    """JSON product lookup used by the sale / purchase entry screens."""

    required_permission = "products.view"

    def get(self, request):
        q = request.GET.get("q", "").strip()
        qs = Product.objects.for_business(request.business).filter(is_active=True)
        if q:
            from django.db.models import Q

            qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode__iexact=q))
        can_see_cost = has_perm(request.membership.role, "products.manage")
        data = []
        for p in qs.order_by("name")[:15]:
            item = {"id": p.id, "name": p.name, "sku": p.sku, "price": str(p.selling_price), "stock": p.current_stock}
            if can_see_cost:
                item["cost"] = str(p.purchase_price)
            data.append(item)
        return JsonResponse({"results": data})
