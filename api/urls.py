from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

router = DefaultRouter()
router.register("categories", views.CategoryViewSet, basename="category")
router.register("suppliers", views.SupplierViewSet, basename="supplier")
router.register("products", views.ProductViewSet, basename="product")
router.register("inventory/transactions", views.StockTransactionViewSet, basename="stocktransaction")
router.register("purchases", views.PurchaseViewSet, basename="purchase")
router.register("customers", views.CustomerViewSet, basename="customer")
router.register("sales", views.SaleViewSet, basename="sale")
router.register("expense-categories", views.ExpenseCategoryViewSet, basename="expensecategory")
router.register("expenses", views.ExpenseViewSet, basename="expense")

urlpatterns = [
    path("auth/token/", views.LoginThrottledTokenView.as_view(), name="token"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", views.MeView.as_view(), name="me"),
    path("analytics/kpis/", views.KPIView.as_view(), name="kpis"),
    path("analytics/insights/", views.InsightsView.as_view(), name="insights"),
    path("reports/<slug:slug>/", views.ReportView.as_view(), name="report"),
    path("ml/demand-forecasts/", views.DemandForecastView.as_view(), name="demand_forecasts"),
    path("ml/sales-forecast/", views.SalesForecastView.as_view(), name="sales_forecast"),
    path("ml/customer-segments/", views.SegmentsView.as_view(), name="segments"),
    path("ml/anomalies/", views.AnomaliesView.as_view(), name="anomalies"),
    path("ml/recommendations/", views.RecommendationsView.as_view(), name="recommendations"),
    path("ml/train/", views.TrainView.as_view(), name="train"),
] + router.urls
