from django.core.management.base import BaseCommand

from businesses.models import Business
from notifications.services import generate_alerts


class Command(BaseCommand):
    help = "Generate low-stock, forecast and overdue-payment notifications for every active business."

    def handle(self, *args, **opts):
        for b in Business.objects.filter(is_active=True):
            n = generate_alerts(b)
            self.stdout.write(f"{b.name}: {n} new alert(s)")
