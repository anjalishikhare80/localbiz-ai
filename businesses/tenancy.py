from .models import BusinessMember


def resolve_membership(user, business_id=None):
    """
    Return the user's active membership for the business they are working in.

    The business is NEVER taken from a URL or form field supplied for a record;
    it is derived from the user's own memberships (session choice or, for the
    API, the X-Business-ID header which must still match a membership).
    """
    qs = BusinessMember.objects.select_related("business").filter(
        user=user, is_active=True, business__is_active=True
    )
    if business_id:
        try:
            membership = qs.filter(business_id=int(business_id)).first()
        except (TypeError, ValueError):
            membership = None
        if membership:
            return membership
    return qs.order_by("id").first()
