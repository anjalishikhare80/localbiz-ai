from core.views import TenantListView
from .models import AuditLog


class AuditLogListView(TenantListView):
    model = AuditLog
    required_permission = "audit.view"
    title = "Audit log"
    search_fields = ["action", "entity_type", "entity_repr", "user__username"]
    columns = [
        ("When", "created_at"),
        ("User", "user.username"),
        ("Action", "action"),
        ("Entity", lambda o: f"{o.entity_type} {o.entity_repr}".strip()),
        ("IP", "ip_address"),
    ]
    paginate_by = 30

    def base_queryset(self):
        return AuditLog.objects.filter(business=self.request.business).select_related("user")
