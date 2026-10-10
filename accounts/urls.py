from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("login/", views.ThrottledLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("register/", views.RegisterView.as_view(), name="register"),
]
