"""
Security tests: tenant isolation (IDOR) and role-based access, exercised through real HTTP requests.
"""
import json
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from catalog.models import Product
from core.testing import PASSWORD, add_member, make_business, make_category, make_customer, make_product, make_supplier
from finance.models import Expense, ExpenseCategory
from sales.services import create_sale


class TwoTenantsMixin:
    @classmethod
    def setUpTestData(cls):
        cls.biz_a, cls.owner_a = make_business("Shop A")
        cls.biz_b, cls.owner_b = make_business("Shop B")
        # data that belongs to B (the "victim")
        cls.b_product = make_product(cls.biz_b, "B-Secret-Pen", stock=50)
        cls.b_customer = make_customer(cls.biz_b, "B-Customer", "9111111111")
        cls.b_supplier = make_supplier(cls.biz_b, "B-Supplier")
        cls.b_category = make_category(cls.biz_b, "B-Cat")
        cls.b_sale = create_sale(business=cls.biz_b, user=cls.owner_b, customer=cls.b_customer,
                                 items=[{"product_id": cls.b_product.id, "quantity": 2}])
        cat = ExpenseCategory.objects.for_business(cls.biz_b).first()
        cls.b_expense = Expense.objects.create(business=cls.biz_b, category=cat, amount=Decimal("10"), receipt=SimpleUploadedFile("r.pdf", b"%PDF-1.4"))
        # A has its own product so the lists are not empty
        cls.a_product = make_product(cls.biz_a, "A-Pen", stock=10)

    def login_a(self):
        self.client.login(username=self.owner_a.username, password=PASSWORD)


class TenantIsolationWebTests(TwoTenantsMixin, TestCase):
    def test_user_a_cannot_open_business_b_objects_by_id(self):
        self.login_a()
        urls = [
            reverse("catalog:product_detail", args=[self.b_product.pk]),
            reverse("catalog:product_edit", args=[self.b_product.pk]),
            reverse("catalog:category_edit", args=[self.b_category.pk]),
            reverse("catalog:supplier_edit", args=[self.b_supplier.pk]),
            reverse("customers:detail", args=[self.b_customer.pk]),
            reverse("customers:edit", args=[self.b_customer.pk]),
            reverse("customers:payment", args=[self.b_customer.pk]),
            reverse("sales:detail", args=[self.b_sale.pk]),
            reverse("sales:invoice_pdf", args=[self.b_sale.pk]),
            reverse("sales:payment", args=[self.b_sale.pk]),
            reverse("finance:expense_edit", args=[self.b_expense.pk]),
            reverse("finance:receipt", args=[self.b_expense.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_user_a_cannot_modify_business_b_objects_by_post(self):
        self.login_a()
        resp = self.client.post(reverse("sales:cancel", args=[self.b_sale.pk]))
        self.b_sale.refresh_from_db()
        self.assertEqual(self.b_sale.status, "COMPLETED")
        self.client.post(reverse("catalog:product_edit", args=[self.b_product.pk]), {"name": "HACKED", "sku": "X", "selling_price": "1"})
        self.b_product.refresh_from_db()
        self.assertEqual(self.b_product.name, "B-Secret-Pen")

    def test_lists_only_show_own_data(self):
        self.login_a()
        self.assertNotContains(self.client.get(reverse("catalog:product_list")), "B-Secret-Pen")
        self.assertContains(self.client.get(reverse("catalog:product_list")), "A-Pen")
        self.assertNotContains(self.client.get(reverse("customers:list")), "B-Customer")
        self.assertNotContains(self.client.get(reverse("sales:list")), self.b_sale.invoice_number)
        self.assertNotContains(self.client.get(reverse("inventory:ledger")), "B-Secret-Pen")
        self.assertNotContains(self.client.get(reverse("catalog:product_search"), {"q": "Secret"}), "B-Secret-Pen")

    def test_sale_post_with_foreign_product_or_customer_is_rejected(self):
        self.login_a()
        for payload in (
            {"items": [{"product_id": self.b_product.id, "quantity": 1}]},
            {"items": [{"product_id": self.a_product.id, "quantity": 1}], "customer_id": self.b_customer.id},
        ):
            resp = self.client.post(reverse("sales:new"), json.dumps(payload), content_type="application/json")
            self.assertIn(resp.status_code, (400, 404))
        self.b_product.refresh_from_db()
        self.assertEqual(self.b_product.current_stock, 48)

    def test_product_form_rejects_foreign_category_and_supplier(self):
        self.login_a()
        resp = self.client.post(reverse("catalog:product_add"), {
            "name": "Sneaky", "sku": "SN-1", "selling_price": "5", "purchase_price": "3", "unit": "pcs",
            "category": self.b_category.pk, "supplier": self.b_supplier.pk, "min_stock_level": 0, "reorder_level": 0, "is_active": "on",
        })
        self.assertEqual(resp.status_code, 200)       # form re-rendered with errors
        self.assertFalse(Product.objects.filter(name="Sneaky").exists())

    def test_same_sku_allowed_in_different_businesses_but_not_within_one(self):
        self.login_a()
        data = {"name": "Dup", "sku": self.b_product.sku, "selling_price": "5", "purchase_price": "3", "unit": "pcs",
                "min_stock_level": 0, "reorder_level": 0, "is_active": "on"}
        self.client.post(reverse("catalog:product_add"), data)
        self.assertEqual(Product.objects.filter(sku=self.b_product.sku).count(), 2)      # ok across tenants
        resp = self.client.post(reverse("catalog:product_add"), data)                      # duplicate inside A
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Product.objects.filter(business=self.biz_a, sku=self.b_product.sku).count(), 1)

    def test_cannot_switch_into_a_business_you_do_not_belong_to(self):
        self.login_a()
        resp = self.client.post(reverse("businesses:switch"), {"business_id": self.biz_b.pk})
        self.assertEqual(resp.status_code, 404)
        self.assertNotEqual(self.client.session.get("business_id"), self.biz_b.pk)

    def test_forged_session_business_id_does_not_grant_access(self):
        self.login_a()
        session = self.client.session
        session["business_id"] = self.biz_b.pk
        session.save()
        self.assertEqual(self.client.get(reverse("catalog:product_detail", args=[self.b_product.pk])).status_code, 404)

    def test_audit_log_is_scoped(self):
        self.login_a()
        from audit.models import AuditLog
        AuditLog.objects.create(business=self.biz_b, user=self.owner_b, action="b.secret.action")
        self.assertNotContains(self.client.get(reverse("audit:list")), "b.secret.action")


class RoleAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.business, cls.owner = make_business("Shop")
        cls.manager = add_member(cls.business, "MANAGER")
        cls.employee = add_member(cls.business, "EMPLOYEE")
        cls.product = make_product(cls.business, "Pen", stock=10)

    def get_as(self, user, url_name, *args):
        self.client.logout()
        self.client.login(username=user.username, password=PASSWORD)
        return self.client.get(reverse(url_name, args=args))

    def test_employee_cannot_reach_owner_or_manager_pages(self):
        for name in ("finance:expense_list", "businesses:team", "businesses:settings", "audit:list", "inventory:ledger",
                     "inventory:adjust", "inventory:purchase_list", "catalog:supplier_list", "catalog:product_add",
                     "ml:overview", "reports:index"):
            with self.subTest(page=name):
                self.assertEqual(self.get_as(self.employee, name).status_code, 403)

    def test_employee_can_use_sales_screens(self):
        for name in ("dashboard", "sales:new", "sales:list", "catalog:product_list", "customers:list"):
            with self.subTest(page=name):
                self.assertEqual(self.get_as(self.employee, name).status_code, 200)

    def test_employee_does_not_see_cost_price_or_profit(self):
        resp = self.get_as(self.employee, "catalog:product_list")
        self.assertNotContains(resp, "Cost")
        resp = self.get_as(self.employee, "dashboard")
        self.assertNotContains(resp, "profit")
        self.client.login(username=self.employee.username, password=PASSWORD)
        data = self.client.get(reverse("catalog:product_search"), {"q": "Pen"}).json()["results"][0]
        self.assertNotIn("cost", data)

    def test_manager_cannot_see_financials_or_admin_pages(self):
        for name in ("finance:expense_list", "businesses:team", "businesses:settings", "audit:list"):
            with self.subTest(page=name):
                self.assertEqual(self.get_as(self.manager, name).status_code, 403)
        self.assertEqual(self.get_as(self.manager, "reports:report", "profit-loss").status_code, 403)
        self.assertEqual(self.get_as(self.manager, "reports:report", "expenses").status_code, 403)
        self.assertNotContains(self.get_as(self.manager, "dashboard"), "Est. net profit")

    def test_manager_can_manage_stock_and_see_sales_reports(self):
        for name in ("inventory:ledger", "inventory:adjust", "catalog:supplier_list", "ml:overview", "reports:index"):
            with self.subTest(page=name):
                self.assertEqual(self.get_as(self.manager, name).status_code, 200)
        self.assertEqual(self.get_as(self.manager, "reports:report", "daily-sales").status_code, 200)

    def test_owner_can_reach_everything(self):
        for name in ("finance:expense_list", "businesses:team", "businesses:settings", "audit:list", "ml:overview"):
            with self.subTest(page=name):
                self.assertEqual(self.get_as(self.owner, name).status_code, 200)
        self.assertContains(self.get_as(self.owner, "dashboard"), "Est. net profit")

    def test_employee_cannot_post_privileged_actions(self):
        self.client.login(username=self.employee.username, password=PASSWORD)
        self.assertEqual(self.client.post(reverse("ml:train")).status_code, 403)
        self.assertEqual(self.client.post(reverse("inventory:adjust"), {"product": self.product.pk, "txn_type": "ADJUSTMENT", "quantity": 5}).status_code, 403)
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, 10)

    def test_anonymous_cannot_reach_anything(self):
        for name in ("dashboard", "sales:list", "catalog:product_list", "ml:overview", "audit:list"):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.get(reverse("catalog:product_search")).status_code, 302)

    def test_deactivated_member_loses_access(self):
        from businesses.models import BusinessMember
        BusinessMember.objects.filter(user=self.employee).update(is_active=False)
        self.client.login(username=self.employee.username, password=PASSWORD)
        resp = self.client.get(reverse("sales:list"))
        self.assertEqual(resp.status_code, 302)          # redirected to "create business": no active membership

    def test_role_changes_are_audited_and_owner_row_is_protected(self):
        from audit.models import AuditLog
        from businesses.models import BusinessMember
        self.client.login(username=self.owner.username, password=PASSWORD)
        m = BusinessMember.objects.get(user=self.employee)
        self.client.post(reverse("businesses:member_edit", args=[m.pk]), {"role": "MANAGER", "is_active": "on"})
        m.refresh_from_db()
        self.assertEqual(m.role, "MANAGER")
        self.assertTrue(AuditLog.objects.filter(action="member.permission_changed").exists())
        owner_member = BusinessMember.objects.get(user=self.owner)
        self.assertEqual(self.client.get(reverse("businesses:member_edit", args=[owner_member.pk])).status_code, 404)

    def test_csrf_is_enforced(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        c.login(username=self.owner.username, password=PASSWORD)
        resp = c.post(reverse("sales:new"), "{}", content_type="application/json")
        self.assertEqual(resp.status_code, 403)
