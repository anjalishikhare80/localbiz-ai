from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.shortcuts import redirect
from django.views.generic import FormView

from businesses.services import create_business_with_owner

from .forms import RegisterForm, StyledAuthForm


def _key(request):
    return f"loginfail:{request.META.get('REMOTE_ADDR', '')}:{request.POST.get('username', '').lower()}"


class ThrottledLoginView(LoginView):
    """Login with a simple brute-force lockout (per IP + username)."""

    template_name = "registration/login.html"
    authentication_form = StyledAuthForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        if cache.get(_key(request), 0) >= settings.LOGIN_MAX_FAILURES:
            form = self.get_form()
            form.add_error(None, "Too many failed attempts. Please try again in a few minutes.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        key = _key(self.request)
        cache.set(key, cache.get(key, 0) + 1, settings.LOGIN_LOCKOUT_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(_key(self.request))
        return super().form_valid(form)


class RegisterView(FormView):
    template_name = "accounts/register.html"
    form_class = RegisterForm

    def form_valid(self, form):
        user = form.save()
        business = create_business_with_owner(
            user=user, name=form.cleaned_data["business_name"],
            business_type=form.cleaned_data["business_type"], request=self.request,
        )
        login(self.request, user)
        self.request.session["business_id"] = business.pk
        return redirect("dashboard")
