from decimal import Decimal

from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Max, Q, Sum, Value
from django.db.models.functions import Coalesce

from audit.services import log as audit_log
from core.exceptions import BusinessRuleError
from core.utils import money

from .models import Customer


def customers_with_stats(business):
    """Customers annotated with total_spent, outstanding, order_count and last_purchase."""
    zero = Value(Decimal("0"), output_field=DecimalField(max_digits=14, decimal_places=2))
    done = Q(sales__status="COMPLETED")
    balance = ExpressionWrapper(F("sales__total") - F("sales__amount_paid"), output_field=DecimalField(max_digits=14, decimal_places=2))
    return Customer.objects.for_business(business).annotate(
        total_spent=Coalesce(Sum("sales__total", filter=done), zero),
        outstanding=Coalesce(Sum(balance, filter=done), zero),
        order_count=Count("sales", filter=done),
        last_purchase=Max("sales__sale_date", filter=done),
    ).order_by("name")


@transaction.atomic
def receive_customer_payment(*, business, user, customer, amount, method="CASH", request=None):
    """Customer pays off their balance. The payment is applied to the oldest unpaid sales first."""
    from sales.models import Payment, Sale

    if customer.business_id != business.id:
        raise BusinessRuleError("Invalid customer.")
    amount = money(amount)
    if amount <= 0:
        raise BusinessRuleError("Amount must be greater than zero.")
    sales = list(
        Sale.objects.select_for_update().filter(business=business, customer=customer, status="COMPLETED")
        .filter(amount_paid__lt=F("total")).order_by("sale_date", "id")
    )
    outstanding = sum((s.total - s.amount_paid for s in sales), Decimal("0"))
    if amount > outstanding:
        raise BusinessRuleError(f"Amount exceeds the outstanding balance of {outstanding:,.2f}.")
    remaining = amount
    for sale in sales:
        if remaining <= 0:
            break
        part = min(remaining, sale.total - sale.amount_paid)
        Payment.objects.create(business=business, sale=sale, customer=customer, amount=part, method=method,
                               created_by=user, note="Balance payment")
        sale.amount_paid += part
        sale.save(update_fields=["amount_paid", "updated_at"])
        remaining -= part
    audit_log(business=business, user=user, action="customer.payment_received", entity=customer,
              metadata={"amount": str(amount), "method": method}, request=request)
    return amount
