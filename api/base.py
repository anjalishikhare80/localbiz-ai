from rest_framework import serializers
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated

from businesses.permissions import has_perm
from businesses.tenancy import resolve_membership

from .permissions import HasBusinessPermission


class BusinessPKField(serializers.PrimaryKeyRelatedField):
    """Foreign-key field that only accepts rows of the requester's business (IDOR guard)."""

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(business=self.context["request"].business)


class TenantAPIMixin:
    """
    Resolves the tenant for every API request and scopes queries to it.
    The business comes from the user's memberships (X-Business-ID header must match one of them),
    never from IDs inside the request body.
    """

    permission_classes = [IsAuthenticated, HasBusinessPermission]
    perm_view = None
    perm_manage = None
    perm_by_action = {}

    def perform_authentication(self, request):
        super().perform_authentication(request)
        request.business = None
        request.membership = None
        if request.user and request.user.is_authenticated:
            membership = resolve_membership(request.user, request.headers.get("X-Business-ID"))
            if membership:
                request.membership = membership
                request.business = membership.business

    def get_required_permission(self):
        action = getattr(self, "action", None)
        if action in self.perm_by_action:
            return self.perm_by_action[action]
        return self.perm_view if self.request.method in SAFE_METHODS else self.perm_manage

    def can(self, perm):
        return has_perm(self.request.membership.role, perm)


class ScopedQuerysetMixin(TenantAPIMixin):
    model = None

    def get_queryset(self):
        return self.model.objects.for_business(self.request.business)

    def perform_create(self, serializer):
        serializer.save(business=self.request.business)
