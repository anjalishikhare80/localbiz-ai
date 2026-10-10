"""End-to-end smoke test: seed the synthetic demo business, then open every page as every role."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from businesses.models import Business
from catalog.models import Product
from inventory.models import StockTransaction
from sales.models import Sale


class DemoSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", days=130, stdout=StringIO())
        cls.business = Business.objects.get(name__contains="DEMO")

    def login(self, username):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password="Demo@12345"))

    def test_seed_is_consistent(self):
        from django.db.models import Sum
        self.assertGreater(Sale.objects.for_business(self.business).count(), 500)
        for p in Product.objects.for_business(self.business):
            ledger = StockTransaction.objects.filter(product=p).aggregate(t=Sum("quantity_change"))["t"] or 0
            self.assertEqual(p.current_stock, ledger, p.name)
            self.assertGreaterEqual(p.current_stock, 0)
        numbers = list(Sale.objects.for_business(self.business).values_list("invoice__number", flat=True))
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_models_were_trained(self):
        from ml.models import ModelVersion
        kinds = set(ModelVersion.objects.for_business(self.business).values_list("kind", flat=True))
        self.assertIn("DEMAND", kinds)
        self.assertIn("SEGMENTS", kinds)
        self.assertIn("ASSOC", kinds)

    def test_owner_can_open_every_page(self):
        self.login("demo_owner")
        sale = Sale.objects.for_business(self.business).first()
        product = Product.objects.for_business(self.business).first()
        from customers.models import Customer
        customer = Customer.objects.for_business(self.business).first()
        pages = [
            reverse("dashboard"), reverse("sales:list"), reverse("sales:new"), reverse("sales:detail", args=[sale.pk]),
            reverse("customers:list"), reverse("customers:detail", args=[customer.pk]), reverse("customers:add"),
            reverse("catalog:product_list"), reverse("catalog:product_detail", args=[product.pk]), reverse("catalog:product_add"),
            reverse("catalog:product_edit", args=[product.pk]), reverse("catalog:category_list"), reverse("catalog:supplier_list"),
            reverse("inventory:ledger"), reverse("inventory:adjust"), reverse("inventory:purchase_list"), reverse("inventory:purchase_add"),
            reverse("finance:expense_list"), reverse("finance:expense_add"), reverse("finance:category_list"),
            reverse("reports:index"), reverse("ml:overview"), reverse("notifications:list"), reverse("audit:list"),
            reverse("businesses:team"), reverse("businesses:settings"), reverse("businesses:member_add"),
        ] + [reverse("reports:report", args=[s]) for s in (
            "daily-sales", "monthly-sales", "profit-loss", "inventory", "low-stock", "customers", "suppliers", "expenses", "tax")]
        for url in pages:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_pdf_invoice_and_csv_export(self):
        self.login("demo_owner")
        sale = Sale.objects.for_business(self.business).first()
        resp = self.client.get(reverse("sales:invoice_pdf", args=[sale.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))
        csv_resp = self.client.get(reverse("reports:report", args=["inventory"]) + "?format=csv")
        self.assertEqual(csv_resp["Content-Type"], "text/csv")
        self.assertIn("Stock value", csv_resp.content.decode())

    def test_dashboard_shows_kpis_insights_and_chart(self):
        self.login("demo_owner")
        html = self.client.get(reverse("dashboard")).content.decode()
        for needle in ("Today's sales", "Est. net profit", "Top products this month", "Business insights", "salesChart"):
            self.assertIn(needle, html)

    def test_ui_flow_new_sale_via_json_endpoint(self):
        import json
        self.login("demo_employee")
        product = Product.objects.for_business(self.business).filter(current_stock__gte=3).first()
        before = product.current_stock
        resp = self.client.post(reverse("sales:new"), json.dumps({"items": [{"product_id": product.id, "quantity": 2}]}), content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        product.refresh_from_db()
        self.assertEqual(product.current_stock, before - 2)
        self.assertTrue(resp.json()["ok"])

    def test_manager_and_employee_pages(self):
        self.login("demo_manager")
        for name in ("dashboard", "inventory:ledger", "ml:overview", "reports:index"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.login("demo_employee")
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("ml:overview")).status_code, 403)

    def test_retrain_button_and_alert_refresh(self):
        self.login("demo_owner")
        self.assertEqual(self.client.post(reverse("ml:train")).status_code, 302)
        self.assertEqual(self.client.post(reverse("notifications:refresh")).status_code, 302)
        self.assertEqual(self.client.post(reverse("notifications:mark_read")).status_code, 302)

    def test_rerunning_seed_without_reset_refuses(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("seed_demo_data", stdout=StringIO())
