from django.urls import path

from . import views

app_name = "inventory"
urlpatterns = [
    path("ledger/", views.StockLedgerView.as_view(), name="ledger"),
    path("adjust/", views.StockAdjustView.as_view(), name="adjust"),
    path("purchases/", views.PurchaseListView.as_view(), name="purchase_list"),
    path("purchases/new/", views.PurchaseCreateView.as_view(), name="purchase_add"),
    path("purchases/<int:pk>/pay/", views.PurchasePayView.as_view(), name="purchase_pay"),
]
