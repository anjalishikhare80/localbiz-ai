from celery import shared_task

from businesses.models import Business

from .services import generate_alerts


@shared_task
def generate_alerts_all():
    total = 0
    for business in Business.objects.filter(is_active=True):
        total += generate_alerts(business)
    return total
