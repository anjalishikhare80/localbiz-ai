from businesses.permissions import perms_for_role


def tenant(request):
    ctx = {"user_perms": set(), "current_business": None, "my_memberships": [], "unread_notifications": 0}
    business = getattr(request, "business", None)
    if business is None:
        return ctx
    membership = request.membership
    ctx["current_business"] = business
    ctx["current_role"] = membership.get_role_display()
    ctx["user_perms"] = perms_for_role(membership.role)
    from businesses.models import BusinessMember
    from notifications.models import Notification

    ctx["my_memberships"] = list(
        BusinessMember.objects.filter(user=request.user, is_active=True, business__is_active=True).select_related("business")
    )
    ctx["unread_notifications"] = Notification.objects.for_business(business).filter(is_read=False).count()
    return ctx
