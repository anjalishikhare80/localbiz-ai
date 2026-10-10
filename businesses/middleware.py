from .tenancy import resolve_membership


class ActiveBusinessMiddleware:
    """Attach request.business and request.membership for web (session) requests."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.business = None
        request.membership = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            membership = resolve_membership(user, request.session.get("business_id"))
            if membership:
                request.membership = membership
                request.business = membership.business
        return self.get_response(request)
