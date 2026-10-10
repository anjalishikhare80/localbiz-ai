from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import CreateView, ListView, UpdateView

from audit.services import log as audit_log
from businesses.permissions import has_perm
from core.exceptions import BusinessRuleError
from core.utils import format_cell


class BusinessViewMixin(LoginRequiredMixin):
    """
    Base for every authenticated page.

    1. user must be logged in;
    2. user must belong to an active business (request.business is set by middleware);
    3. the user's role must hold ``required_permission``.
    """

    required_permission = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if getattr(request, "business", None) is None:
            return redirect("businesses:create")
        if self.required_permission and not has_perm(request.membership.role, self.required_permission):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def _resolve(obj, path):
    value = obj
    for part in path.split("."):
        if value is None:
            return None
        value = getattr(value, part, None)
        if callable(value):
            value = value()
    return value


class TenantListView(BusinessViewMixin, ListView):
    """Generic searchable, paginated table. Subclasses set ``model`` and ``columns``."""

    template_name = "core/list.html"
    paginate_by = 20
    title = ""
    columns = []  # list of (label, "attr.path" | callable(obj))
    search_fields = []
    create_url_name = None
    create_label = "Add new"
    create_permission = None
    edit_url_name = None
    edit_permission = None
    detail_url_name = None
    extra_actions = []  # list of (label, url_name, permission)

    def get_columns(self):
        return self.columns

    def base_queryset(self):
        """Tenant-scoped rows. Models that are not TenantModels override this."""
        return self.model.objects.for_business(self.request.business)

    def get_queryset(self):
        qs = self.base_queryset()
        q = self.request.GET.get("q", "").strip()
        if q and self.search_fields:
            cond = Q()
            for f in self.search_fields:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)
        return self.filter_queryset(qs)

    def filter_queryset(self, qs):
        return qs

    def _can(self, perm):
        return perm is None or has_perm(self.request.membership.role, perm)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        columns = self.get_columns()
        rows = []
        for obj in ctx["object_list"]:
            cells = []
            for _, accessor in columns:
                value = accessor(obj) if callable(accessor) else _resolve(obj, accessor)
                cells.append(format_cell(value))
            actions = []
            if self.detail_url_name:
                actions.append(("View", reverse(self.detail_url_name, args=[obj.pk])))
            if self.edit_url_name and self._can(self.edit_permission):
                actions.append(("Edit", reverse(self.edit_url_name, args=[obj.pk])))
            for label, url_name, perm in self.extra_actions:
                if self._can(perm):
                    actions.append((label, reverse(url_name, args=[obj.pk])))
            rows.append({"cells": cells, "actions": actions})
        ctx.update(
            title=self.title,
            headers=[c[0] for c in columns],
            rows=rows,
            q=self.request.GET.get("q", ""),
            has_search=bool(self.search_fields),
            create_url=reverse(self.create_url_name) if self.create_url_name and self._can(self.create_permission) else None,
            create_label=self.create_label,
            querystring=self._querystring(),
        )
        return ctx

    def _querystring(self):
        params = self.request.GET.copy()
        params.pop("page", None)
        return params.urlencode()


class TenantFormMixin(BusinessViewMixin):
    """Shared logic for create / update of a tenant-owned model."""

    template_name = "core/form.html"
    title = ""
    success_url_name = None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["business"] = self.request.business
        return kwargs

    def get_queryset(self):
        return self.model.objects.for_business(self.request.business)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = self.title
        ctx["cancel_url"] = reverse(self.success_url_name)
        return ctx

    def get_success_url(self):
        return reverse(self.success_url_name)

    def before_save(self, obj, form):
        pass

    def after_save(self, obj, form, created):
        pass

    def form_valid(self, form):
        created = form.instance.pk is None
        try:
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.business = self.request.business
                if created and hasattr(obj, "created_by_id"):
                    obj.created_by = self.request.user
                self.before_save(obj, form)
                obj.save()
                form.save_m2m()
                self.after_save(obj, form, created)
                audit_log(
                    business=self.request.business,
                    user=self.request.user,
                    action=f"{obj._meta.model_name}.{'created' if created else 'updated'}",
                    entity=obj,
                    request=self.request,
                )
        except BusinessRuleError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        self.object = obj
        messages.success(self.request, f"{obj._meta.verbose_name.title()} saved.")
        return redirect(self.get_success_url())


class TenantCreateView(TenantFormMixin, CreateView):
    pass


class TenantUpdateView(TenantFormMixin, UpdateView):
    pass
