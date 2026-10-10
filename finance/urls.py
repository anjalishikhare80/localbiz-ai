from django.urls import path

from . import views

app_name = "finance"
urlpatterns = [
    path("expenses/", views.ExpenseListView.as_view(), name="expense_list"),
    path("expenses/add/", views.ExpenseCreateView.as_view(), name="expense_add"),
    path("expenses/<int:pk>/edit/", views.ExpenseUpdateView.as_view(), name="expense_edit"),
    path("expenses/<int:pk>/receipt/", views.ReceiptView.as_view(), name="receipt"),
    path("categories/", views.CategoryListView.as_view(), name="category_list"),
    path("categories/add/", views.CategoryCreateView.as_view(), name="category_add"),
    path("categories/<int:pk>/edit/", views.CategoryUpdateView.as_view(), name="category_edit"),
]
