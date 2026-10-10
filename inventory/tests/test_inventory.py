from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.test import TestCase

from catalog.models import Product
from core.exceptions import BusinessRuleError, InsufficientStock
from core.testing import make_business, make_product, make_supplier
from inventory.models import StockTransaction
from inventory.services import adjust_stock, manual_adjustment, pay_supplier, receive_purchase


class StockLedgerTests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business()
        self.product = make_product(self.business, stock=100)

    def test_every_change_creates_a_ledger_row_and_updates_cache(self):
        adjust_stock(business=self.business, product=self.product, quantity_change=-10, txn_type="SALE", user=self.owner,
                     reference_type="sale", reference_id=123)
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, 90)
        txn = StockTransaction.objects.filter(product=self.product).first()
        self.assertEqual((txn.txn_type, txn.quantity_change, txn.stock_after, txn.reference_id), ("SALE", -10, 90, 123))

    def test_cannot_go_below_zero(self):
        with self.assertRaises(InsufficientStock):
            adjust_stock(business=self.business, product=self.product, quantity_change=-101, txn_type="SALE")
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, 100)

    def test_ledger_sum_always_equals_cached_stock(self):
        adjust_stock(business=self.business, product=self.product, quantity_change=-30, txn_type="SALE")
        adjust_stock(business=self.business, product=self.product, quantity_change=5, txn_type="RETURN_IN")
        self.product.refresh_from_db()
        total = StockTransaction.objects.filter(product=self.product).aggregate(t=Sum("quantity_change"))["t"]
        self.assertEqual(total, self.product.current_stock)

    def test_database_rejects_negative_stock_even_if_service_is_bypassed(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.filter(pk=self.product.pk).update(current_stock=-1)

    def test_cannot_adjust_another_businesses_product(self):
        other, _ = make_business("Shop B")
        with self.assertRaises(BusinessRuleError):
            adjust_stock(business=other, product=self.product, quantity_change=5, txn_type="ADJUSTMENT")

    def test_manual_adjustment_signs(self):
        manual_adjustment(business=self.business, user=self.owner, product=self.product, txn_type="DAMAGE", quantity=4)
        manual_adjustment(business=self.business, user=self.owner, product=self.product, txn_type="RETURN_IN", quantity=2)
        manual_adjustment(business=self.business, user=self.owner, product=self.product, txn_type="ADJUSTMENT", quantity=-3)
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, 100 - 4 + 2 - 3)

    def test_reconcile_command_detects_and_fixes_drift(self):
        Product.objects.filter(pk=self.product.pk).update(current_stock=5)
        out = StringIO()
        call_command("reconcile_stock", stdout=out)
        self.assertIn("mismatch", out.getvalue())
        call_command("reconcile_stock", "--fix", stdout=StringIO())
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, 100)


class PurchaseTests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business()
        self.supplier = make_supplier(self.business)
        self.p1 = make_product(self.business, "Paper", stock=0)
        self.p2 = make_product(self.business, "Pen", stock=2)

    def test_purchase_adds_stock_and_totals(self):
        purchase = receive_purchase(
            business=self.business, user=self.owner, supplier=self.supplier, paid_amount=100,
            items=[{"product_id": self.p1.id, "quantity": 10, "unit_cost": "20.00"}, {"product_id": self.p2.id, "quantity": 5, "unit_cost": "4.00"}],
        )
        self.p1.refresh_from_db(); self.p2.refresh_from_db()
        self.assertEqual((self.p1.current_stock, self.p2.current_stock), (10, 7))
        self.assertEqual(purchase.total_amount, 220)
        self.assertEqual(purchase.balance, 120)
        self.assertEqual(StockTransaction.objects.filter(txn_type="PURCHASE").count(), 2)

    def test_failed_purchase_saves_nothing(self):
        with self.assertRaises(BusinessRuleError):
            receive_purchase(business=self.business, user=self.owner, supplier=self.supplier,
                             items=[{"product_id": self.p1.id, "quantity": 10, "unit_cost": "20"}, {"product_id": 99999, "quantity": 1, "unit_cost": "1"}])
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.current_stock, 0)

    def test_pay_supplier_cannot_overpay(self):
        purchase = receive_purchase(business=self.business, user=self.owner, supplier=self.supplier,
                                    items=[{"product_id": self.p1.id, "quantity": 1, "unit_cost": "50"}])
        pay_supplier(business=self.business, user=self.owner, purchase_id=purchase.pk, amount=30)
        with self.assertRaises(BusinessRuleError):
            pay_supplier(business=self.business, user=self.owner, purchase_id=purchase.pk, amount=30)
