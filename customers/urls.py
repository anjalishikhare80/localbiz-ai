from django.urls import path

from . import views

app_name = "customers"
urlpatterns = [
    path("", views.CustomerListView.as_view(), name="list"),
    path("add/", views.CustomerCreateView.as_view(), name="add"),
    path("<int:pk>/", views.CustomerDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.CustomerUpdateView.as_view(), name="edit"),
    path("<int:pk>/payment/", views.CustomerPaymentView.as_view(), name="payment"),
]
