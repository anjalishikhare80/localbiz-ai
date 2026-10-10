from django.urls import path

from . import views

app_name = "sales"
urlpatterns = [
    path("", views.SaleListView.as_view(), name="list"),
    path("new/", views.SaleCreateView.as_view(), name="new"),
    path("<int:pk>/", views.SaleDetailView.as_view(), name="detail"),
    path("<int:pk>/cancel/", views.SaleCancelView.as_view(), name="cancel"),
    path("<int:pk>/payment/", views.SalePaymentView.as_view(), name="payment"),
    path("<int:pk>/invoice.pdf", views.InvoicePDFView.as_view(), name="invoice_pdf"),
]
