from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from audit.services import log as audit_log
from businesses.models import BusinessSequence
from catalog.models import Product
from core.exceptions import BusinessRuleError
from core.utils import TWOPLACES, money
from inventory.models import StockTransaction
from inventory.services import adjust_stock

from .models import Invoice, Payment, Sale, SaleItem


def _normalise_items(items):
    merged = {}
    for it in items or []:
        try:
            pid = int(it["product_id"])
            qty = int(it["quantity"])
            discount = Decimal(str(it.get("discount") or 0))
        except (KeyError, ValueError, TypeError, ArithmeticError):
            raise BusinessRuleError("Invalid item data.")
        if qty <= 0:
            raise BusinessRuleError("Quantity must be at least 1.")
        if discount < 0:
            raise BusinessRuleError("Discount cannot be negative.")
        row = merged.setdefault(pid, {"quantity": 0, "discount": Decimal("0")})
        row["quantity"] += qty
        row["discount"] += discount
    if not merged:
        raise BusinessRuleError("A sale needs at least one item.")
    return merged


@transaction.atomic
def create_sale(*, business, user, items, customer=None, payment_method="CASH", amount_paid=None,
                note="", sale_date=None, request=None, log_audit=True):
    """
    Create a complete sale in ONE database transaction:
    sale + items + stock reduction (ledger) + payment + invoice + audit record.
    If anything fails (e.g. not enough stock) nothing is saved.
    """
    merged = _normalise_items(items)
    if customer is not None and customer.business_id != business.id:
        raise BusinessRuleError("Invalid customer.")
    if payment_method not in Sale.Method.values:
        raise BusinessRuleError("Invalid payment method.")

    products = {p.id: p for p in Product.objects.for_business(business).filter(id__in=merged.keys(), is_active=True)}
    if len(products) != len(merged):
        raise BusinessRuleError("One or more products were not found or are inactive.")

    lines, subtotal = [], Decimal("0")
    for pid in sorted(merged):  # fixed order -> no deadlocks between concurrent sales
        p, qty, discount = products[pid], merged[pid]["quantity"], money(merged[pid]["discount"])
        gross = p.selling_price * qty
        if discount > gross:
            raise BusinessRuleError(f"Discount for {p.name} is larger than the line amount.")
        line_total = gross - discount
        subtotal += line_total
        lines.append((p, qty, discount, line_total))

    tax = (subtotal * business.tax_rate / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    total = subtotal + tax
    paid = total if amount_paid is None else money(amount_paid)
    if paid < 0 or paid > total:
        raise BusinessRuleError("Amount paid must be between 0 and the sale total.")
    if paid < total and customer is None:
        raise BusinessRuleError("Select a customer for credit or part-payment sales.")

    sale_date = sale_date or timezone.now()
    sale = Sale.objects.create(
        business=business, customer=customer, sale_date=sale_date, subtotal=subtotal, tax_amount=tax,
        total=total, amount_paid=paid, payment_method=payment_method, note=note[:255],
        created_by=user if getattr(user, "pk", None) else None,
    )
    for p, qty, discount, line_total in lines:
        SaleItem.objects.create(
            sale=sale, product=p, product_name=p.name, quantity=qty, unit_price=p.selling_price,
            cost_price=p.purchase_price, discount=discount, line_total=line_total,
        )
        adjust_stock(  # raises InsufficientStock -> whole sale rolls back
            business=business, product=p, quantity_change=-qty, txn_type=StockTransaction.TxnType.SALE,
            user=user, reference_type="sale", reference_id=sale.pk, occurred_at=sale_date,
        )
    if paid > 0:
        Payment.objects.create(business=business, sale=sale, customer=customer, amount=paid, method=payment_method,
                               paid_at=sale_date, created_by=user if getattr(user, "pk", None) else None)
    year = timezone.localtime(sale_date).year
    number = f"{business.invoice_prefix}-{year}-{BusinessSequence.next_value(business, f'invoice-{year}'):06d}"
    Invoice.objects.create(business=business, sale=sale, number=number, issued_at=sale_date)
    if log_audit:
        audit_log(business=business, user=user, action="sale.created", entity=sale,
                  metadata={"invoice": number, "total": str(total), "items": len(lines)}, request=request)
    return sale


@transaction.atomic
def cancel_sale(*, business, user, sale_id, request=None):
    """Void a sale: stock is returned through the ledger and the sale stops counting in reports."""
    sale = Sale.objects.select_for_update().filter(business=business, pk=sale_id).first()
    if not sale:
        raise BusinessRuleError("Sale not found.")
    if sale.status == Sale.Status.CANCELLED:
        raise BusinessRuleError("This sale is already cancelled.")
    for item in sale.items.select_related("product"):
        adjust_stock(
            business=business, product=item.product, quantity_change=item.quantity,
            txn_type=StockTransaction.TxnType.SALE_CANCEL, user=user, reference_type="sale", reference_id=sale.pk,
            note=f"Cancelled {sale.invoice_number}",
        )
    sale.status = Sale.Status.CANCELLED
    sale.save(update_fields=["status", "updated_at"])
    audit_log(business=business, user=user, action="sale.cancelled", entity=sale,
              metadata={"invoice": sale.invoice_number, "total": str(sale.total)}, request=request)
    return sale


@transaction.atomic
def record_payment(*, business, user, sale_id, amount, method="CASH", note="", request=None):
    sale = Sale.objects.select_for_update().filter(business=business, pk=sale_id).first()
    if not sale:
        raise BusinessRuleError("Sale not found.")
    if sale.status != Sale.Status.COMPLETED:
        raise BusinessRuleError("Payments can only be added to completed sales.")
    amount = money(amount)
    if amount <= 0 or amount > sale.balance:
        raise BusinessRuleError(f"Amount must be between 0.01 and the balance due ({sale.balance:,.2f}).")
    Payment.objects.create(business=business, sale=sale, customer=sale.customer, amount=amount, method=method,
                           created_by=user, note=note[:255])
    sale.amount_paid += amount
    sale.save(update_fields=["amount_paid", "updated_at"])
    audit_log(business=business, user=user, action="payment.recorded", entity=sale,
              metadata={"amount": str(amount), "method": method}, request=request)
    return sale
