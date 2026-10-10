from decimal import Decimal

from django.test import TestCase

from audit.models import AuditLog
from catalog.models import Product
from core.exceptions import BusinessRuleError, InsufficientStock
from core.testing import make_business, make_customer, make_product
from customers.services import customers_with_stats, receive_customer_payment
from inventory.models import StockTransaction
from sales.models import Invoice, Payment, Sale, SaleItem
from sales.services import cancel_sale, create_sale, record_payment


class CreateSaleTests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business()
        self.pen = make_product(self.business, "Pen", price="10.00", cost="6.00", stock=100)
        self.book = make_product(self.business, "Book", price="50.00", cost="30.00", stock=20)

    def sale(self, items=None, **kw):
        items = items or [{"product_id": self.pen.id, "quantity": 10}]
        return create_sale(business=self.business, user=self.owner, items=items, **kw)

    def test_sale_creates_everything_in_one_go(self):
        sale = self.sale()
        self.pen.refresh_from_db()
        self.assertEqual(self.pen.current_stock, 90)                          # stock reduced
        self.assertEqual(sale.items.count(), 1)                               # sale items
        self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)        # payment
        self.assertTrue(Invoice.objects.filter(sale=sale).exists())           # invoice
        self.assertTrue(AuditLog.objects.filter(action="sale.created", entity_id=str(sale.pk)).exists())  # audit
        txn = StockTransaction.objects.get(reference_type="sale", reference_id=sale.pk)
        self.assertEqual((txn.txn_type, txn.quantity_change, txn.stock_after), ("SALE", -10, 90))
        self.assertEqual(sale.total, Decimal("100.00"))
        self.assertEqual(sale.payment_status, "Paid")

    def test_insufficient_stock_rolls_back_everything(self):
        with self.assertRaises(InsufficientStock):
            self.sale([{"product_id": self.pen.id, "quantity": 5}, {"product_id": self.book.id, "quantity": 21}])
        self.pen.refresh_from_db(); self.book.refresh_from_db()
        self.assertEqual((self.pen.current_stock, self.book.current_stock), (100, 20))   # nothing partially saved
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertEqual(StockTransaction.objects.filter(txn_type="SALE").count(), 0)

    def test_tax_and_discount_calculation(self):
        self.business.tax_rate = Decimal("5.00")
        self.business.save()
        sale = self.sale([{"product_id": self.book.id, "quantity": 2, "discount": "10.00"}])
        self.assertEqual(sale.subtotal, Decimal("90.00"))      # 2*50 - 10
        self.assertEqual(sale.tax_amount, Decimal("4.50"))     # 5% of 90
        self.assertEqual(sale.total, Decimal("94.50"))

    def test_discount_larger_than_line_is_rejected(self):
        with self.assertRaises(BusinessRuleError):
            self.sale([{"product_id": self.pen.id, "quantity": 1, "discount": "11"}])

    def test_duplicate_lines_are_merged(self):
        sale = self.sale([{"product_id": self.pen.id, "quantity": 2}, {"product_id": self.pen.id, "quantity": 3}])
        self.assertEqual(sale.items.get().quantity, 5)

    def test_invalid_quantities_and_empty_sale(self):
        for bad in ([{"product_id": self.pen.id, "quantity": 0}], [{"product_id": self.pen.id, "quantity": -2}], [{"quantity": 1}]):
            with self.assertRaises(BusinessRuleError):
                self.sale(bad)
        with self.assertRaises(BusinessRuleError):
            create_sale(business=self.business, user=self.owner, items=[])

    def test_credit_sale_needs_a_customer(self):
        with self.assertRaises(BusinessRuleError):
            self.sale(amount_paid=0)
        customer = make_customer(self.business, "Ravi")
        sale = self.sale(amount_paid="40", customer=customer)
        self.assertEqual(sale.payment_status, "Partial")
        self.assertEqual(sale.balance, Decimal("60.00"))

    def test_paid_amount_cannot_exceed_total(self):
        with self.assertRaises(BusinessRuleError):
            self.sale(amount_paid="1000")

    def test_invoice_numbers_are_unique_and_sequential(self):
        numbers = [self.sale().invoice.number for _ in range(3)]
        self.assertEqual(len(set(numbers)), 3)
        self.assertTrue(numbers[0].endswith("000001") and numbers[2].endswith("000003"))

    def test_invoice_numbers_are_per_business(self):
        other, other_owner = make_business("Shop B")
        p = make_product(other, "Pen", stock=10)
        s = create_sale(business=other, user=other_owner, items=[{"product_id": p.id, "quantity": 1}])
        self.assertTrue(s.invoice.number.endswith("000001"))

    def test_sale_item_prices_are_snapshots(self):
        sale = self.sale()
        self.pen.selling_price = Decimal("99.00"); self.pen.purchase_price = Decimal("50.00"); self.pen.save()
        item = SaleItem.objects.get(sale=sale)
        self.assertEqual((item.unit_price, item.cost_price), (Decimal("10.00"), Decimal("6.00")))

    def test_cannot_sell_another_businesses_product_or_to_their_customer(self):
        other, _ = make_business("Shop B")
        foreign_product = make_product(other, "Secret", stock=5)
        with self.assertRaises(BusinessRuleError):
            self.sale([{"product_id": foreign_product.id, "quantity": 1}])
        with self.assertRaises(BusinessRuleError):
            self.sale(customer=make_customer(other, "Their customer"))

    def test_inactive_product_cannot_be_sold(self):
        Product.objects.filter(pk=self.pen.pk).update(is_active=False)
        with self.assertRaises(BusinessRuleError):
            self.sale()


class CancelAndPaymentTests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business()
        self.pen = make_product(self.business, "Pen", price="10.00", stock=50)
        self.customer = make_customer(self.business, "Ravi")

    def make(self, qty, paid=None):
        return create_sale(business=self.business, user=self.owner, customer=self.customer, amount_paid=paid,
                           items=[{"product_id": self.pen.id, "quantity": qty}])

    def test_cancel_restores_stock_via_ledger_and_excludes_from_totals(self):
        sale = self.make(10)
        cancel_sale(business=self.business, user=self.owner, sale_id=sale.pk)
        self.pen.refresh_from_db()
        self.assertEqual(self.pen.current_stock, 50)
        self.assertTrue(StockTransaction.objects.filter(txn_type="SALE_CANCEL", quantity_change=10).exists())
        self.assertEqual(customers_with_stats(self.business).get().total_spent, 0)
        with self.assertRaises(BusinessRuleError):
            cancel_sale(business=self.business, user=self.owner, sale_id=sale.pk)

    def test_record_payment_updates_balance_and_blocks_overpayment(self):
        sale = self.make(10, paid=20)                        # total 100, paid 20
        record_payment(business=self.business, user=self.owner, sale_id=sale.pk, amount=30)
        sale.refresh_from_db()
        self.assertEqual(sale.balance, Decimal("50.00"))
        with self.assertRaises(BusinessRuleError):
            record_payment(business=self.business, user=self.owner, sale_id=sale.pk, amount=51)

    def test_customer_payment_is_applied_oldest_first(self):
        s1 = self.make(10, paid=0)      # 100 owed (older)
        s2 = self.make(5, paid=0)       # 50 owed
        receive_customer_payment(business=self.business, user=self.owner, customer=self.customer, amount=120)
        s1.refresh_from_db(); s2.refresh_from_db()
        self.assertEqual(s1.balance, 0)
        self.assertEqual(s2.balance, Decimal("30.00"))
        stats = customers_with_stats(self.business).get()
        self.assertEqual(stats.outstanding, Decimal("30.00"))
        self.assertEqual(stats.total_spent, Decimal("150.00"))
        with self.assertRaises(BusinessRuleError):
            receive_customer_payment(business=self.business, user=self.owner, customer=self.customer, amount=31)
