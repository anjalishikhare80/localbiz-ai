import threading
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from core.exceptions import BusinessRuleError
from core.testing import make_business, make_product
from sales.models import Sale
from sales.services import create_sale


@skipUnless(connection.vendor == "postgresql", "row-level locking needs PostgreSQL")
class ConcurrentSaleTests(TransactionTestCase):
    """Two cashiers sell the LAST unit at the same moment: exactly one may succeed."""

    def test_no_overselling_under_concurrency(self):
        business, owner = make_business()
        product = make_product(business, "Last One", stock=1)
        results, barrier = [], threading.Barrier(2)

        def cashier():
            try:
                barrier.wait()
                create_sale(business=business, user=owner, items=[{"product_id": product.id, "quantity": 1}])
                results.append("sold")
            except BusinessRuleError:
                results.append("refused")
            finally:
                close_old_connections()
                connection.close()

        threads = [threading.Thread(target=cashier) for _ in range(2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        product.refresh_from_db()
        self.assertEqual(sorted(results), ["refused", "sold"])
        self.assertEqual(product.current_stock, 0)
        self.assertEqual(Sale.objects.count(), 1)

    def test_concurrent_invoice_numbers_never_collide(self):
        business, owner = make_business()
        product = make_product(business, "Plenty", stock=100)
        numbers, barrier = [], threading.Barrier(4)

        def cashier():
            try:
                barrier.wait()
                sale = create_sale(business=business, user=owner, items=[{"product_id": product.id, "quantity": 1}])
                numbers.append(sale.invoice.number)
            finally:
                close_old_connections()
                connection.close()

        threads = [threading.Thread(target=cashier) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(numbers), 4)
        self.assertEqual(len(set(numbers)), 4)
