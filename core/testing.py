"""Small factory helpers shared by the test-suites."""
from decimal import Decimal
from itertools import count

from django.contrib.auth import get_user_model

from businesses.models import BusinessMember
from businesses.services import create_business_with_owner
from catalog.models import Category, Product, Supplier
from customers.models import Customer
from inventory.models import StockTransaction
from inventory.services import adjust_stock

User = get_user_model()
_seq = count(1)
PASSWORD = "TestPass#12345"


def make_user(username=None, **kw):
    n = next(_seq)
    username = username or f"user{n}"
    return User.objects.create_user(username=username, email=f"{username}@example.com", password=PASSWORD, **kw)


def make_business(name="Shop A", owner_name=None):
    owner = make_user(owner_name)
    business = create_business_with_owner(user=owner, name=name)
    return business, owner


def add_member(business, role, username=None):
    user = make_user(username)
    BusinessMember.objects.create(user=user, business=business, role=role)
    return user


def make_product(business, name="Pen", sku=None, price="10.00", cost="6.00", stock=0, **kw):
    sku = sku or f"SKU{next(_seq)}"
    p = Product.objects.create(business=business, name=name, sku=sku, selling_price=Decimal(price), purchase_price=Decimal(cost),
                               reorder_level=kw.pop("reorder_level", 5), **kw)
    if stock:
        adjust_stock(business=business, product=p, quantity_change=stock, txn_type=StockTransaction.TxnType.OPENING)
        p.refresh_from_db()
    return p


def make_customer(business, name="Customer", phone=""):
    return Customer.objects.create(business=business, name=name, phone=phone)


def make_supplier(business, name="Supplier"):
    return Supplier.objects.create(business=business, name=name)


def make_category(business, name="General"):
    return Category.objects.create(business=business, name=name)
