from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from audit.models import AuditLog
from businesses.models import Business, BusinessMember
from core.testing import PASSWORD, make_business


class UserModelTests(TestCase):
    def test_create_user_hashes_password(self):
        User = get_user_model()
        user = User.objects.create_user(username="anjali", email="anjali@example.com", password="StrongPass#123")
        self.assertTrue(user.check_password("StrongPass#123"))
        self.assertNotEqual(user.password, "StrongPass#123")

    def test_email_must_be_unique(self):
        User = get_user_model()
        User.objects.create_user(username="user1", email="same@example.com", password="StrongPass#123")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(username="user2", email="same@example.com", password="StrongPass#123")


class RegistrationAndLoginTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_registration_creates_business_owner_and_default_categories(self):
        resp = self.client.post(reverse("accounts:register"), {
            "username": "newowner", "email": "new@example.com", "password1": PASSWORD, "password2": PASSWORD,
            "business_name": "Fresh Bakery", "business_type": "BAKERY",
        })
        self.assertRedirects(resp, reverse("dashboard"))
        business = Business.objects.get(name="Fresh Bakery")
        member = BusinessMember.objects.get(business=business)
        self.assertEqual(member.role, "OWNER")
        from finance.models import ExpenseCategory
        self.assertTrue(ExpenseCategory.objects.filter(business=business, name="Rent").exists())

    def test_login_is_audited(self):
        business, owner = make_business()
        self.client.post(reverse("accounts:login"), {"username": owner.username, "password": PASSWORD})
        self.assertTrue(AuditLog.objects.filter(user=owner, action="user.login").exists())

    def test_login_lockout_after_repeated_failures(self):
        business, owner = make_business()
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": owner.username, "password": "wrong"})
        resp = self.client.post(reverse("accounts:login"), {"username": owner.username, "password": PASSWORD})
        self.assertEqual(resp.status_code, 429)

    def test_anonymous_is_redirected_to_login(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])
