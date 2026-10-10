from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from catalog.models import Product
from core.testing import PASSWORD, add_member, make_business, make_category, make_customer, make_product, make_supplier
from sales.models import Sale
from sales.services import create_sale

API = "/api/v1/"


def client_for(user, business_id=None):
    cache.clear()  # reset rate-limit counters so tests never throttle each other
    c = APIClient()
    resp = c.post(API + "auth/token/", {"username": user.username, "password": PASSWORD}, format="json")
    assert resp.status_code == 200, resp.content
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}", **({"HTTP_X_BUSINESS_ID": str(business_id)} if business_id else {}))
    return c


class AuthTests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business()

    def test_token_login_and_bad_credentials(self):
        ok = APIClient().post(API + "auth/token/", {"username": self.owner.username, "password": PASSWORD}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertIn("access", ok.data)
        bad = APIClient().post(API + "auth/token/", {"username": self.owner.username, "password": "nope"}, format="json")
        self.assertEqual(bad.status_code, 401)

    def test_unauthenticated_requests_are_rejected(self):
        for path in ("products/", "sales/", "customers/", "analytics/kpis/", "ml/demand-forecasts/"):
            self.assertEqual(APIClient().get(API + path).status_code, 401, path)

    def test_invalid_token_is_rejected(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        self.assertEqual(c.get(API + "products/").status_code, 401)

    def test_me_endpoint(self):
        data = client_for(self.owner).get(API + "me/").data
        self.assertEqual(data["active_business"]["role"], "OWNER")

    def test_user_without_business_is_forbidden(self):
        from core.testing import make_user
        lonely = make_user()
        self.assertEqual(client_for(lonely).get(API + "products/").status_code, 403)


class ProductAPITests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business()
        self.employee = add_member(self.business, "EMPLOYEE")
        self.api = client_for(self.owner)

    def test_crud_with_opening_stock_creates_ledger(self):
        r = self.api.post(API + "products/", {"name": "Pen", "sku": "P1", "selling_price": "10.00", "purchase_price": "6.00", "opening_stock": 25}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["current_stock"], 0 + 25)
        pid = r.data["id"]
        self.assertEqual(self.api.get(API + f"inventory/transactions/?product={pid}").data["count"], 1)
        r = self.api.patch(API + f"products/{pid}/", {"selling_price": "12.00", "current_stock": 999}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["selling_price"], "12.00")
        self.assertEqual(r.data["current_stock"], 25)            # stock is read-only
        self.assertEqual(self.api.delete(API + f"products/{pid}/").status_code, 204)
        self.assertFalse(Product.objects.get(pk=pid).is_active)    # soft delete

    def test_validation_errors_use_consistent_format(self):
        r = self.api.post(API + "products/", {"name": "", "sku": "", "selling_price": "-5"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"]["status"], 400)
        self.assertEqual(r.data["error"]["message"], "Validation failed.")
        self.assertIn("name", r.data["error"]["details"])

    def test_duplicate_sku_is_rejected(self):
        make_product(self.business, sku="DUP")
        r = self.api.post(API + "products/", {"name": "x", "sku": "DUP", "selling_price": "1"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_pagination_search_ordering_filtering(self):
        for i in range(25):
            make_product(self.business, f"Item {i:02d}", stock=i)
        r = self.api.get(API + "products/")
        self.assertEqual((r.data["count"], len(r.data["results"])), (25, 20))
        self.assertIsNotNone(r.data["next"])
        self.assertEqual(self.api.get(API + "products/?search=Item 07").data["count"], 1)
        self.assertEqual(self.api.get(API + "products/?ordering=-name").data["results"][0]["name"], "Item 24")
        self.assertGreaterEqual(self.api.get(API + "products/?low_stock=true").data["count"], 5)

    def test_employee_can_read_but_not_write_and_does_not_see_cost(self):
        make_product(self.business, "Pen", cost="6.00")
        emp = client_for(self.employee)
        r = emp.get(API + "products/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("purchase_price", r.data["results"][0])
        self.assertIn("purchase_price", self.api.get(API + "products/").data["results"][0])
        self.assertEqual(emp.post(API + "products/", {"name": "x", "sku": "x", "selling_price": "1"}, format="json").status_code, 403)

    def test_employee_blocked_from_owner_resources(self):
        emp = client_for(self.employee)
        for path in ("expenses/", "suppliers/", "purchases/", "ml/demand-forecasts/", "analytics/kpis/", "reports/profit-loss/", "inventory/transactions/"):
            self.assertEqual(emp.get(API + path).status_code, 403, path)
        self.assertEqual(emp.post(API + "ml/train/").status_code, 403)

    def test_manager_cannot_use_expenses_or_financial_reports(self):
        mgr = client_for(add_member(self.business, "MANAGER"))
        self.assertEqual(mgr.get(API + "expenses/").status_code, 403)
        self.assertEqual(mgr.get(API + "reports/profit-loss/").status_code, 403)
        self.assertEqual(mgr.get(API + "reports/daily-sales/").status_code, 200)
        self.assertNotIn("month_net_profit", mgr.get(API + "analytics/kpis/").data)
        self.assertIn("month_net_profit", self.api.get(API + "analytics/kpis/").data)


class APITenantIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.biz_a, cls.owner_a = make_business("A")
        cls.biz_b, cls.owner_b = make_business("B")
        cls.b_product = make_product(cls.biz_b, "B-Pen", stock=10)
        cls.b_customer = make_customer(cls.biz_b, "B-Cust")
        cls.b_supplier = make_supplier(cls.biz_b)
        cls.b_cat = make_category(cls.biz_b)
        cls.b_sale = create_sale(business=cls.biz_b, user=cls.owner_b, items=[{"product_id": cls.b_product.id, "quantity": 1}])
        cls.a_product = make_product(cls.biz_a, "A-Pen", stock=10)

    def setUp(self):
        self.api = client_for(self.owner_a)

    def test_detail_update_delete_of_foreign_objects_is_404(self):
        for path in (f"products/{self.b_product.pk}/", f"customers/{self.b_customer.pk}/", f"suppliers/{self.b_supplier.pk}/",
                     f"categories/{self.b_cat.pk}/", f"sales/{self.b_sale.pk}/"):
            with self.subTest(path=path):
                self.assertEqual(self.api.get(API + path).status_code, 404)
                if not path.startswith("sales/"):          # sales are read-only: PATCH/DELETE give 405 anyway
                    self.assertEqual(self.api.patch(API + path, {"name": "hacked"}, format="json").status_code, 404)
                    self.assertEqual(self.api.delete(API + path).status_code, 404)
        self.assertEqual(self.api.post(API + f"sales/{self.b_sale.pk}/cancel/").status_code, 404)
        self.assertEqual(self.api.post(API + f"customers/{self.b_customer.pk}/receive-payment/", {"amount": "1"}, format="json").status_code, 404)
        self.b_product.refresh_from_db()
        self.assertEqual(self.b_product.name, "B-Pen")

    def test_lists_never_contain_foreign_rows(self):
        names = [p["name"] for p in self.api.get(API + "products/").data["results"]]
        self.assertEqual(names, ["A-Pen"])
        self.assertEqual(self.api.get(API + "sales/").data["count"], 0)
        self.assertEqual(self.api.get(API + "customers/").data["count"], 0)

    def test_foreign_foreign_keys_in_request_body_are_rejected(self):
        r = self.api.post(API + "products/", {"name": "x", "sku": "x1", "selling_price": "1", "category": self.b_cat.pk}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api.post(API + "sales/", {"items": [{"product": self.b_product.pk, "quantity": 1}]}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api.post(API + "sales/", {"customer": self.b_customer.pk, "items": [{"product": self.a_product.pk, "quantity": 1}]}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api.post(API + "inventory/transactions/adjust/", {"product": self.b_product.pk, "txn_type": "ADJUSTMENT", "quantity": 100}, format="json")
        self.assertEqual(r.status_code, 400)
        self.b_product.refresh_from_db()
        self.assertEqual(self.b_product.current_stock, 9)

    def test_x_business_id_header_cannot_select_a_foreign_business(self):
        api = client_for(self.owner_a, business_id=self.biz_b.pk)   # A tries to claim B
        names = [p["name"] for p in api.get(API + "products/").data["results"]]
        self.assertEqual(names, ["A-Pen"])                           # silently falls back to A's own business
        self.assertEqual(api.get(API + f"products/{self.b_product.pk}/").status_code, 404)

    def test_non_numeric_and_missing_ids(self):
        self.assertEqual(self.api.get(API + "products/abc/").status_code, 404)
        self.assertEqual(self.api.get(API + "products/999999/").status_code, 404)
        self.assertEqual(self.api.get(API + "products/-1/").status_code, 404)


class SalesAPITests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business()
        self.employee = add_member(self.business, "EMPLOYEE")
        self.pen = make_product(self.business, "Pen", price="10.00", stock=20)
        self.api = client_for(self.owner)

    def test_create_sale_reduces_stock_and_returns_invoice(self):
        r = self.api.post(API + "sales/", {"items": [{"product": self.pen.pk, "quantity": 4, "discount": "2.00"}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["total"], "38.00")
        self.assertTrue(r.data["invoice_number"].startswith("INV-"))
        self.assertEqual(r.data["payment_status"], "Paid")
        self.pen.refresh_from_db()
        self.assertEqual(self.pen.current_stock, 16)

    def test_insufficient_stock_returns_400_and_changes_nothing(self):
        r = self.api.post(API + "sales/", {"items": [{"product": self.pen.pk, "quantity": 21}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Not enough stock", r.data["error"]["message"])
        self.assertEqual(Sale.objects.count(), 0)

    def test_invalid_input(self):
        bad = [{"items": []}, {"items": [{"product": self.pen.pk, "quantity": 0}]}, {"items": [{"product": self.pen.pk, "quantity": "abc"}]},
               {"items": [{"product": self.pen.pk, "quantity": 1, "discount": "-1"}]}, {}]
        for payload in bad:
            self.assertEqual(self.api.post(API + "sales/", payload, format="json").status_code, 400, payload)

    def test_employee_can_sell_but_not_cancel(self):
        emp = client_for(self.employee)
        r = emp.post(API + "sales/", {"items": [{"product": self.pen.pk, "quantity": 1}]}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(emp.post(API + f"sales/{r.data['id']}/cancel/").status_code, 403)
        self.assertEqual(self.api.post(API + f"sales/{r.data['id']}/cancel/").status_code, 200)
        self.pen.refresh_from_db()
        self.assertEqual(self.pen.current_stock, 20)

    def test_partial_payment_flow(self):
        cust = make_customer(self.business, "Ravi")
        r = self.api.post(API + "sales/", {"customer": cust.pk, "amount_paid": "5.00", "items": [{"product": self.pen.pk, "quantity": 2}]}, format="json")
        self.assertEqual((r.data["payment_status"], r.data["balance"]), ("Partial", "15.00"))
        r2 = self.api.post(API + f"sales/{r.data['id']}/payments/", {"amount": "15.00"}, format="json")
        self.assertEqual(r2.data["payment_status"], "Paid")
        over = self.api.post(API + f"sales/{r.data['id']}/payments/", {"amount": "1.00"}, format="json")
        self.assertEqual(over.status_code, 400)

    def test_kpis_and_insights_endpoints(self):
        self.api.post(API + "sales/", {"items": [{"product": self.pen.pk, "quantity": 3}]}, format="json")
        k = self.api.get(API + "analytics/kpis/").data
        self.assertEqual(Decimal(k["today_sales"]), Decimal("30.00"))
        self.assertEqual(self.api.get(API + "analytics/insights/").status_code, 200)

    def test_ml_endpoints_exist_and_are_empty_without_training(self):
        for path in ("ml/demand-forecasts/", "ml/sales-forecast/", "ml/customer-segments/", "ml/anomalies/", "ml/recommendations/"):
            r = self.api.get(API + path)
            self.assertEqual(r.status_code, 200, path)
            self.assertEqual(r.data, [])
        r = self.api.post(API + "ml/train/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["demand"]["status"], "insufficient_data")

    def test_expenses_owner_crud(self):
        from finance.models import ExpenseCategory
        cat = ExpenseCategory.objects.for_business(self.business).first()
        r = self.api.post(API + "expenses/", {"category": cat.pk, "amount": "100.00", "expense_date": "2026-01-05"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.api.post(API + "expenses/", {"category": cat.pk, "amount": "-5", "expense_date": "2026-01-05"}, format="json").status_code, 400)

    def test_purchase_via_api_adds_stock(self):
        sup = make_supplier(self.business)
        r = self.api.post(API + "purchases/", {"supplier": sup.pk, "items": [{"product": self.pen.pk, "quantity": 10, "unit_cost": "5.00"}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.pen.refresh_from_db()
        self.assertEqual(self.pen.current_stock, 30)

    def test_report_endpoint_json(self):
        r = self.api.get(API + "reports/inventory/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.api.get(API + "reports/does-not-exist/").status_code, 404)
