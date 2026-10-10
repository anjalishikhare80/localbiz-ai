from django.urls import path

from . import views

app_name = "notifications"
urlpatterns = [
    path("", views.NotificationListView.as_view(), name="list"),
    path("mark-read/", views.MarkReadView.as_view(), name="mark_read"),
    path("refresh/", views.RefreshView.as_view(), name="refresh"),
]
