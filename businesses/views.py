from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import FormView, UpdateView

from audit.services import log as audit_log
from core.exceptions import BusinessRuleError
from core.views import BusinessViewMixin, TenantListView

from .forms import BusinessCreateForm, BusinessSettingsForm, MemberCreateForm, MemberUpdateForm
from .models import BusinessMember
from .services import add_member, create_business_with_owner


class BusinessCreateView(LoginRequiredMixin, FormView):
    template_name = "core/form.html"
    form_class = BusinessCreateForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(title="Create your business", cancel_url=reverse("accounts:login"))
        return ctx

    def form_valid(self, form):
        business = create_business_with_owner(
            user=self.request.user, name=form.cleaned_data["name"],
            business_type=form.cleaned_data["business_type"], request=self.request,
        )
        self.request.session["business_id"] = business.pk
        return redirect("dashboard")


class SwitchBusinessView(LoginRequiredMixin, View):
    def post(self, request):
        business_id = request.POST.get("business_id")
        # Only switch to a business the user actually belongs to.
        membership = BusinessMember.objects.filter(user=request.user, is_active=True, business_id=business_id).first()
        if not membership:
            raise Http404
        request.session["business_id"] = membership.business_id
        return redirect("dashboard")


class SettingsView(BusinessViewMixin, UpdateView):
    required_permission = "settings.manage"
    form_class = BusinessSettingsForm
    template_name = "core/form.html"

    def get_object(self, queryset=None):
        return self.request.business

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(title="Business settings", cancel_url=reverse("dashboard"))
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        audit_log(business=self.request.business, user=self.request.user, action="business.updated",
                  entity=self.object, request=self.request)
        messages.success(self.request, "Settings saved.")
        return response

    def get_success_url(self):
        return reverse("businesses:settings")


class TeamListView(TenantListView):
    model = BusinessMember
    required_permission = "team.manage"
    title = "Team"
    create_url_name = "businesses:member_add"
    create_label = "Add team member"
    create_permission = "team.manage"
    edit_url_name = "businesses:member_edit"
    edit_permission = "team.manage"
    columns = [
        ("Username", "user.username"),
        ("E-mail", "user.email"),
        ("Role", "get_role_display"),
        ("Active", "is_active"),
    ]

    def base_queryset(self):
        # BusinessMember is not a TenantModel, so scope explicitly.
        return BusinessMember.objects.filter(business=self.request.business).select_related("user").order_by("role", "user__username")


class MemberAddView(BusinessViewMixin, FormView):
    required_permission = "team.manage"
    form_class = MemberCreateForm
    template_name = "core/form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(title="Add team member", cancel_url=reverse("businesses:team"))
        return ctx

    def form_valid(self, form):
        try:
            add_member(business=self.request.business, actor=self.request.user, request=self.request, **form.cleaned_data)
        except BusinessRuleError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Team member added.")
        return redirect("businesses:team")


class MemberEditView(BusinessViewMixin, UpdateView):
    required_permission = "team.manage"
    form_class = MemberUpdateForm
    template_name = "core/form.html"

    def get_object(self, queryset=None):
        # Scoped to this business; the owner row cannot be edited here.
        return get_object_or_404(
            BusinessMember.objects.exclude(role=BusinessMember.Role.OWNER),
            pk=self.kwargs["pk"], business=self.request.business,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(title=f"Edit {self.object.user.username}", cancel_url=reverse("businesses:team"))
        return ctx

    def form_valid(self, form):
        old_role = BusinessMember.objects.get(pk=self.object.pk).role
        response = super().form_valid(form)
        audit_log(
            business=self.request.business, user=self.request.user, action="member.permission_changed",
            entity=self.object, metadata={"old_role": old_role, "new_role": self.object.role, "active": self.object.is_active},
            request=self.request,
        )
        messages.success(self.request, "Team member updated.")
        return response

    def get_success_url(self):
        return reverse("businesses:team")
