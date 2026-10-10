import csv
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.http import HttpResponse
from django.utils import timezone

TWOPLACES = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def day_start(d=None):
    """Aware datetime for local midnight of date ``d`` (default today)."""
    d = d or timezone.localdate()
    return timezone.make_aware(datetime.combine(d, time.min))


def next_day_start(d=None):
    d = d or timezone.localdate()
    return day_start(d + timedelta(days=1))


def month_start(d=None):
    d = d or timezone.localdate()
    return day_start(d.replace(day=1))


def format_cell(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%d %b %Y %H:%M") if timezone.is_aware(value) else value.strftime("%d %b %Y %H:%M")
    return str(value)


def _csv_safe(value):
    """Neutralise spreadsheet formula injection (cells starting with = + - @)."""
    s = "" if value is None else str(value)
    if s and s[0] in "=+-@":
        return "'" + s
    return s


def csv_response(filename, headers, rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow([_csv_safe(h) for h in headers])
    for row in rows:
        writer.writerow([_csv_safe(c) for c in row])
    return response
