from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from analytics import services
from analytics.insights import generate_insights
from core.testing import make_business, make_customer, make_product
from core.utils import _csv_safe, csv_response, day_start, next_day_start
from finance.models import Expense, ExpenseCategory
from sales.services import create_sale


class ProfitTests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business()
        self.pen = make_product(self.business, "Pen", price="10.00", cost="6.00", stock=100)

    def test_gross_and_net_profit(self):
        create_sale(business=self.business, user=self.owner, items=[{"product_id": self.pen.id, "quantity": 10, "discount": "5"}])  # revenue 95, cost 60
        cat = ExpenseCategory.objects.for_business(self.business).get(name="Rent")
        Expense.objects.create(business=self.business, category=cat, amount=Decimal("20"), expense_date=timezone.localdate())
        today = timezone.localdate()
        pl = services.profit_loss(self.business, today, today)
        self.assertEqual(pl["revenue"], Decimal("95.00"))
        self.assertEqual(pl["gross_profit"], Decimal("35.00"))   # 95 - 60
        self.assertEqual(pl["expenses"], Decimal("20.00"))
        self.assertEqual(pl["net_profit"], Decimal("15.00"))

    def test_cancelled_sales_do_not_count(self):
        from sales.services import cancel_sale

        sale = create_sale(business=self.business, user=self.owner, items=[{"product_id": self.pen.id, "quantity": 10}])
        cancel_sale(business=self.business, user=self.owner, sale_id=sale.pk)
        k = services.kpis(self.business)
        self.assertEqual(k["today_sales"], 0)
        self.assertEqual(k["month_gross_profit"], 0)

    def test_kpis_inventory_value_and_receivables(self):
        customer = make_customer(self.business, "Ravi")
        create_sale(business=self.business, user=self.owner, customer=customer, amount_paid=0,
                    items=[{"product_id": self.pen.id, "quantity": 10}])
        k = services.kpis(self.business)
        self.assertEqual(k["inventory_value"], Decimal("540.00"))     # 90 left * cost 6
        self.assertEqual(k["outstanding"], Decimal("100.00"))
        self.assertEqual(k["today_count"], 1)
        self.assertEqual(k["top_products"][0]["product_name"], "Pen")

    def test_employee_kpis_have_no_financial_keys(self):
        k = services.kpis(self.business, financial=False)
        self.assertNotIn("month_net_profit", k)
        self.assertNotIn("inventory_value", k)

    def test_low_stock_count(self):
        make_product(self.business, "Rare", stock=2, reorder_level=5)
        self.assertEqual(services.kpis(self.business)["low_stock_count"], 1)

    def test_insights_come_from_real_data(self):
        self.assertEqual(generate_insights(self.business), [])  # no data -> no invented insights
        create_sale(business=self.business, user=self.owner, items=[{"product_id": self.pen.id, "quantity": 95}])
        texts = " ".join(i["text"] for i in generate_insights(self.business))
        self.assertIn("Pen", texts)   # stock cover warning for the product that is nearly gone


class CsvSafetyTests(TestCase):
    def test_formula_injection_is_neutralised(self):
        self.assertEqual(_csv_safe("=HYPERLINK('x')"), "'=HYPERLINK('x')")
        self.assertEqual(_csv_safe("+1"), "'+1")
        self.assertEqual(_csv_safe("normal"), "normal")
        resp = csv_response("x.csv", ["a"], [["=cmd"]])
        self.assertIn("'=cmd", resp.content.decode())
