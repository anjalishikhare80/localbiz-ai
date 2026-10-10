from datetime import datetime, time
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from audit.services import log as audit_log
from catalog.models import Product, Supplier
from core.exceptions import BusinessRuleError, InsufficientStock
from core.utils import money

from .models import Purchase, PurchaseItem, StockTransaction


@transaction.atomic
def adjust_stock(*, business, product, quantity_change, txn_type, user=None,
                 reference_type="", reference_id=None, note="", occurred_at=None):
    """
    THE ONLY function that changes Product.current_stock.

    * locks the product row so two simultaneous sales cannot oversell;
    * refuses to go below zero;
    * writes the ledger row in the same database transaction.
    """
    if quantity_change == 0:
        raise BusinessRuleError("Quantity change cannot be zero.")
    try:
        locked = Product.objects.select_for_update().get(pk=product.pk, business=business)
    except Product.DoesNotExist:
        raise BusinessRuleError("Product not found.")
    new_stock = locked.current_stock + quantity_change
    if new_stock < 0:
        raise InsufficientStock(
            f"Not enough stock for {locked.name}: {locked.current_stock} available, {-quantity_change} requested."
        )
    locked.current_stock = new_stock
    locked.save(update_fields=["current_stock", "updated_at"])
    product.current_stock = new_stock  # keep the caller's instance in sync
    return StockTransaction.objects.create(
        business=business, product=locked, txn_type=txn_type, quantity_change=quantity_change,
        stock_after=new_stock, reference_type=reference_type, reference_id=reference_id,
        note=note[:255], created_by=user if getattr(user, "pk", None) else None,
        occurred_at=occurred_at or timezone.now(),
    )


MANUAL_TYPES = {
    # txn_type: sign applied to the (positive) quantity entered by the user
    StockTransaction.TxnType.ADJUSTMENT: None,   # signed by the user
    StockTransaction.TxnType.DAMAGE: -1,
    StockTransaction.TxnType.RETURN_IN: 1,
    StockTransaction.TxnType.RETURN_OUT: -1,
}


@transaction.atomic
def manual_adjustment(*, business, user, product, txn_type, quantity, note="", request=None):
    if txn_type not in MANUAL_TYPES:
        raise BusinessRuleError("Unsupported adjustment type.")
    sign = MANUAL_TYPES[txn_type]
    change = int(quantity) if sign is None else sign * abs(int(quantity))
    txn = adjust_stock(
        business=business, product=product, quantity_change=change, txn_type=txn_type,
        user=user, reference_type="manual", note=note,
    )
    audit_log(
        business=business, user=user, action="inventory.adjusted", entity=product,
        metadata={"type": txn_type, "change": change, "stock_after": txn.stock_after, "note": note}, request=request,
    )
    return txn


@transaction.atomic
def receive_purchase(*, business, user, supplier, items, paid_amount=0, purchase_date=None, note="",
                     update_cost_price=True, request=None, log_audit=True):
    """
    Record stock bought from a supplier. ``items``: [{"product_id", "quantity", "unit_cost"}].
    Creates the purchase, its items, and one ledger row per item (all-or-nothing).
    """
    if supplier.business_id != business.id:
        raise BusinessRuleError("Invalid supplier.")
    if not items:
        raise BusinessRuleError("A purchase needs at least one item.")
    merged = {}
    for it in items:
        pid, qty, cost = int(it["product_id"]), int(it["quantity"]), money(it["unit_cost"])
        if qty <= 0 or cost < 0:
            raise BusinessRuleError("Quantity must be positive and cost cannot be negative.")
        if pid in merged:
            raise BusinessRuleError("Each product may appear only once per purchase.")
        merged[pid] = (qty, cost)
    products = {p.id: p for p in Product.objects.for_business(business).filter(id__in=merged.keys())}
    if len(products) != len(merged):
        raise BusinessRuleError("One or more products were not found.")
    total = sum((qty * cost for qty, cost in merged.values()), Decimal("0"))
    paid = money(paid_amount or 0)
    if paid < 0 or paid > total:
        raise BusinessRuleError("Paid amount must be between 0 and the purchase total.")
    purchase = Purchase.objects.create(
        business=business, supplier=supplier, purchase_date=purchase_date or timezone.localdate(),
        total_amount=total, paid_amount=paid, note=note[:255], created_by=user if getattr(user, "pk", None) else None,
    )
    for pid in sorted(merged):
        qty, cost = merged[pid]
        product = products[pid]
        PurchaseItem.objects.create(purchase=purchase, product=product, quantity=qty, unit_cost=cost)
        adjust_stock(
            business=business, product=product, quantity_change=qty, txn_type=StockTransaction.TxnType.PURCHASE,
            user=user, reference_type="purchase", reference_id=purchase.pk,
            occurred_at=timezone.now() if purchase_date is None else timezone.make_aware(
                datetime.combine(purchase_date, time(8, 0))
            ),
        )
        if update_cost_price and product.purchase_price != cost:
            Product.objects.filter(pk=product.pk).update(purchase_price=cost)
    if log_audit:
        audit_log(business=business, user=user, action="purchase.created", entity=purchase,
                  metadata={"total": str(total), "items": len(merged)}, request=request)
    return purchase


@transaction.atomic
def pay_supplier(*, business, user, purchase_id, amount, request=None):
    purchase = Purchase.objects.select_for_update().filter(business=business, pk=purchase_id).first()
    if not purchase:
        raise BusinessRuleError("Purchase not found.")
    amount = money(amount)
    if amount <= 0 or amount > purchase.balance:
        raise BusinessRuleError(f"Amount must be between 0.01 and the outstanding balance ({purchase.balance}).")
    purchase.paid_amount += amount
    purchase.save(update_fields=["paid_amount", "updated_at"])
    audit_log(business=business, user=user, action="purchase.paid", entity=purchase, metadata={"amount": str(amount)}, request=request)
    return purchase
