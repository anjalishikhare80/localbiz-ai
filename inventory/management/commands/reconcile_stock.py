from django.core.management.base import BaseCommand
from django.db.models import Sum

from catalog.models import Product
from inventory.models import StockTransaction


class Command(BaseCommand):
    help = "Compare Product.current_stock with the sum of the stock ledger. Use --fix to repair the cache."

    def add_arguments(self, parser):
        parser.add_argument("--fix", action="store_true", help="Overwrite current_stock with the ledger total.")

    def handle(self, *args, **opts):
        totals = dict(StockTransaction.objects.values_list("product_id").annotate(t=Sum("quantity_change")))
        mismatches = 0
        for p in Product.objects.all().iterator():
            expected = totals.get(p.id, 0)
            if p.current_stock != expected:
                mismatches += 1
                self.stdout.write(self.style.WARNING(f"{p} (business {p.business_id}): cache={p.current_stock} ledger={expected}"))
                if opts["fix"]:
                    Product.objects.filter(pk=p.pk).update(current_stock=expected)
        if mismatches:
            self.stdout.write(self.style.WARNING(f"{mismatches} mismatch(es){' fixed' if opts['fix'] else ''}."))
        else:
            self.stdout.write(self.style.SUCCESS("Stock cache matches the ledger for every product."))
