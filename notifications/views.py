from django.shortcuts import redirect
from django.views import View

from core.views import BusinessViewMixin, TenantListView

from .models import Notification
from .services import generate_alerts


class NotificationListView(TenantListView):
    model = Notification
    required_permission = "notifications.view"
    title = "Notifications"
    template_name = "notifications/list.html"
    columns = [("When", "created_at"), ("Type", "get_kind_display"), ("Alert", "title"), ("Details", "message"), ("Read", "is_read")]


class MarkReadView(BusinessViewMixin, View):
    required_permission = "notifications.view"

    def post(self, request):
        Notification.objects.for_business(request.business).filter(is_read=False).update(is_read=True)
        return redirect("notifications:list")


class RefreshView(BusinessViewMixin, View):
    required_permission = "notifications.view"

    def post(self, request):
        generate_alerts(request.business)
        return redirect("notifications:list")
