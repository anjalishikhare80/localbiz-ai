from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views import View

from audit.services import log as audit_log
from core.views import BusinessViewMixin, TenantCreateView, TenantListView, TenantUpdateView

from .forms import ExpenseCategoryForm, ExpenseForm
from .models import Expense, ExpenseCategory


class ExpenseListView(TenantListView):
    model = Expense
    required_permission = "expenses.manage"
    title = "Expenses"
    search_fields = ["description", "category__name"]
    create_url_name = "finance:expense_add"
    create_permission = "expenses.manage"
    edit_url_name = "finance:expense_edit"
    edit_permission = "expenses.manage"
    columns = [
        ("Date", "expense_date"),
        ("Category", "category.name"),
        ("Description", "description"),
        ("Amount", "amount"),
        ("Method", "get_payment_method_display"),
        ("Receipt", lambda o: "Yes" if o.receipt else ""),
    ]
    extra_actions = []

    def filter_queryset(self, qs):
        return qs.select_related("category")


class ExpenseCreateView(TenantCreateView):
    model = Expense
    form_class = ExpenseForm
    required_permission = "expenses.manage"
    title = "Add expense"
    success_url_name = "finance:expense_list"


class ExpenseUpdateView(TenantUpdateView):
    model = Expense
    form_class = ExpenseForm
    required_permission = "expenses.manage"
    title = "Edit expense"
    success_url_name = "finance:expense_list"


class CategoryListView(TenantListView):
    model = ExpenseCategory
    required_permission = "expenses.manage"
    title = "Expense categories"
    search_fields = ["name"]
    columns = [("Name", "name")]
    create_url_name = "finance:category_add"
    create_permission = "expenses.manage"
    edit_url_name = "finance:category_edit"
    edit_permission = "expenses.manage"


class CategoryCreateView(TenantCreateView):
    model = ExpenseCategory
    form_class = ExpenseCategoryForm
    required_permission = "expenses.manage"
    title = "Add expense category"
    success_url_name = "finance:category_list"


class CategoryUpdateView(TenantUpdateView):
    model = ExpenseCategory
    form_class = ExpenseCategoryForm
    required_permission = "expenses.manage"
    title = "Edit expense category"
    success_url_name = "finance:category_list"


class ReceiptView(BusinessViewMixin, View):
    """Receipts are private: streamed only to authorised members of the owning business."""

    required_permission = "expenses.manage"

    def get(self, request, pk):
        expense = get_object_or_404(Expense.objects.for_business(request.business), pk=pk)
        if not expense.receipt:
            raise Http404
        audit_log(business=request.business, user=request.user, action="receipt.viewed", entity=expense, request=request)
        return FileResponse(expense.receipt.open("rb"), as_attachment=False)
