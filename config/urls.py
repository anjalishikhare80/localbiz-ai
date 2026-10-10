from django.contrib import admin
from django.urls import include, path

from analytics.views import DashboardView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", DashboardView.as_view(), name="dashboard"),
    path("accounts/", include("accounts.urls")),
    path("business/", include("businesses.urls")),
    path("catalog/", include("catalog.urls")),
    path("inventory/", include("inventory.urls")),
    path("customers/", include("customers.urls")),
    path("sales/", include("sales.urls")),
    path("finance/", include("finance.urls")),
    path("reports/", include("analytics.urls")),
    path("ml/", include("ml.urls")),
    path("notifications/", include("notifications.urls")),
    path("audit/", include("audit.urls")),
    path("api/v1/", include("api.urls")),
]
