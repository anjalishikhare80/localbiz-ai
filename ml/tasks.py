from celery import shared_task

from businesses.models import Business

from .services import run_all


@shared_task
def train_all_businesses():
    results = {}
    for business in Business.objects.filter(is_active=True):
        results[business.pk] = run_all(business)
    return results
