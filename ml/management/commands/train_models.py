import json

from django.core.management.base import BaseCommand, CommandError

from businesses.models import Business
from ml.services import run_all


class Command(BaseCommand):
    help = "Train / refresh all ML models for one business (--business ID) or every active business (--all)."

    def add_arguments(self, parser):
        parser.add_argument("--business", type=int)
        parser.add_argument("--all", action="store_true")

    def handle(self, *args, **opts):
        if opts["business"]:
            qs = Business.objects.filter(pk=opts["business"])
        elif opts["all"]:
            qs = Business.objects.filter(is_active=True)
        else:
            raise CommandError("Pass --business <id> or --all.")
        for b in qs:
            self.stdout.write(self.style.MIGRATE_HEADING(f"Training models for {b.name} (id={b.pk})"))
            self.stdout.write(json.dumps(run_all(b), indent=2, default=str))
