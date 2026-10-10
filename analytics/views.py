from datetime import date, timedelta

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils import timezone
from django.views.generic import TemplateView

from audit.services import log as audit_log
from businesses.permissions import has_perm
from core.utils import csv_response, format_cell
from core.views import BusinessViewMixin

from . import services
from .insights import generate_insights
from .reports import REPORTS


class DashboardView(BusinessViewMixin, TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        role = self.request.membership.role
        business = self.request.business
        ctx["can_analytics"] = has_perm(role, "analytics.sales")
        ctx["can_financial"] = has_perm(role, "analytics.financial")
        if ctx["can_analytics"]:
            ctx["k"] = services.kpis(business, financial=ctx["can_financial"])
            series = services.sales_by_day(business, 30)
            ctx["chart_labels"] = [d.strftime("%d %b") for d, _ in series]
            ctx["chart_values"] = [float(v) for _, v in series]
            ctx["insights"] = generate_insights(business)[:8]
        else:
            # Employees: no financial data, just what they need to start selling.
            ctx["k"] = None
        return ctx


def _parse_date(value, default):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


class ReportIndexView(BusinessViewMixin, TemplateView):
    required_permission = "reports.view"
    template_name = "reports/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        role = self.request.membership.role
        ctx["reports"] = [(slug, title) for slug, (title, _, perm, _) in REPORTS.items() if has_perm(role, perm)]
        return ctx


class ReportView(BusinessViewMixin, TemplateView):
    required_permission = "reports.view"
    template_name = "reports/report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        slug = self.kwargs["slug"]
        if slug not in REPORTS:
            raise Http404
        title, builder, perm, needs_dates = REPORTS[slug]
        if not has_perm(self.request.membership.role, perm):
            raise PermissionDenied
        today = timezone.localdate()
        start = _parse_date(self.request.GET.get("start"), today - timedelta(days=29))
        end = _parse_date(self.request.GET.get("end"), today)
        headers, rows = builder(self.request.business, start, end)
        ctx.update(title=title, slug=slug, headers=headers, raw_rows=rows, needs_dates=needs_dates, start=start, end=end)
        ctx["rows"] = [[format_cell(c) for c in r] for r in rows]
        return ctx

    def render_to_response(self, context, **kwargs):
        if self.request.GET.get("format") == "csv":
            audit_log(business=self.request.business, user=self.request.user, action="report.exported",
                      metadata={"report": context["slug"]}, request=self.request)
            return csv_response(f"{context['slug']}.csv", context["headers"], context["raw_rows"])
        return super().render_to_response(context, **kwargs)
