from rest_framework.permissions import SAFE_METHODS, BasePermission

from businesses.permissions import has_perm


class HasBusinessPermission(BasePermission):
    """
    Requires an active membership in a business AND a role holding the permission
    that the view declares (perm_view for reads, perm_manage for writes, or perm_by_action).
    """

    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        membership = getattr(request, "membership", None)
        if membership is None:
            self.message = "You are not an active member of any business."
            return False
        perm = view.get_required_permission()
        return perm is None or has_perm(membership.role, perm)
