from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from businesses.permissions import has_perm
from catalog.models import Category, Product, Supplier
from customers.models import Customer
from finance.models import Expense, ExpenseCategory
from inventory.models import Purchase, PurchaseItem, StockTransaction
from inventory.services import adjust_stock
from ml.models import AnomalyFlag, CustomerSegment, DemandForecast, ProductAssociation, SalesForecast
from sales.models import Payment, Sale, SaleItem

from .base import BusinessPKField


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]

    def validate_name(self, value):
        qs = Category.objects.for_business(self.context["request"].business).filter(name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A category with this name already exists.")
        return value


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "contact_person", "phone", "email", "address", "is_active"]

    def validate_name(self, value):
        qs = Supplier.objects.for_business(self.context["request"].business).filter(name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A supplier with this name already exists.")
        return value


class ProductSerializer(serializers.ModelSerializer):
    category = BusinessPKField(queryset=Category.objects.all(), required=False, allow_null=True)
    supplier = BusinessPKField(queryset=Supplier.objects.all(), required=False, allow_null=True)
    opening_stock = serializers.IntegerField(write_only=True, required=False, min_value=0, default=0)

    class Meta:
        model = Product
        fields = ["id", "name", "sku", "barcode", "category", "supplier", "unit", "purchase_price", "selling_price",
                  "current_stock", "min_stock_level", "reorder_level", "is_active", "opening_stock"]
        read_only_fields = ["current_stock"]

    def validate_sku(self, value):
        qs = Product.objects.for_business(self.context["request"].business).filter(sku__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A product with this SKU already exists.")
        return value

    def validate_barcode(self, value):
        if not value:
            return value
        qs = Product.objects.for_business(self.context["request"].business).filter(barcode=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A product with this barcode already exists.")
        return value

    def validate(self, attrs):
        if attrs.get("selling_price") is not None and attrs["selling_price"] < 0:
            raise serializers.ValidationError({"selling_price": "Cannot be negative."})
        if attrs.get("purchase_price") is not None and attrs["purchase_price"] < 0:
            raise serializers.ValidationError({"purchase_price": "Cannot be negative."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        opening = validated_data.pop("opening_stock", 0)
        request = self.context["request"]
        product = Product.objects.create(**validated_data)
        if opening:
            adjust_stock(business=product.business, product=product, quantity_change=opening,
                         txn_type=StockTransaction.TxnType.OPENING, user=request.user, note="Opening stock")
        return product

    def update(self, instance, validated_data):
        validated_data.pop("opening_stock", None)
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request is not None and getattr(request, "membership", None) and not has_perm(request.membership.role, "products.manage"):
            data.pop("purchase_price", None)  # cost price is not shown to employees
        return data


class StockTransactionSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    created_by = serializers.CharField(source="created_by.username", read_only=True, default=None)

    class Meta:
        model = StockTransaction
        fields = ["id", "product", "product_name", "txn_type", "quantity_change", "stock_after", "reference_type",
                  "reference_id", "note", "created_by", "occurred_at"]


class StockAdjustSerializer(serializers.Serializer):
    product = BusinessPKField(queryset=Product.objects.all())
    txn_type = serializers.ChoiceField(choices=["ADJUSTMENT", "DAMAGE", "RETURN_IN", "RETURN_OUT"])
    quantity = serializers.IntegerField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")

    def validate_quantity(self, value):
        if value == 0:
            raise serializers.ValidationError("Quantity cannot be zero.")
        return value


class CustomerSerializer(serializers.ModelSerializer):
    total_spent = serializers.SerializerMethodField()
    outstanding = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = ["id", "name", "phone", "email", "address", "is_active", "total_spent", "outstanding"]

    def get_total_spent(self, obj):
        return str(getattr(obj, "total_spent", Decimal("0")))

    def get_outstanding(self, obj):
        return str(getattr(obj, "outstanding", Decimal("0")))

    def validate_phone(self, value):
        if not value:
            return value
        qs = Customer.objects.for_business(self.context["request"].business).filter(phone=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A customer with this phone number already exists.")
        return value


class SaleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SaleItem
        fields = ["product", "product_name", "quantity", "unit_price", "discount", "line_total"]


class SaleSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True, default=None)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    payment_status = serializers.CharField(read_only=True)
    items = SaleItemSerializer(many=True, read_only=True)

    class Meta:
        model = Sale
        fields = ["id", "invoice_number", "customer", "customer_name", "sale_date", "subtotal", "tax_amount", "total",
                  "amount_paid", "balance", "payment_status", "payment_method", "status", "note", "items"]


class SaleLineInputSerializer(serializers.Serializer):
    product = BusinessPKField(queryset=Product.objects.all())
    quantity = serializers.IntegerField(min_value=1)
    discount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False, default=Decimal("0"))


class SaleCreateSerializer(serializers.Serializer):
    customer = BusinessPKField(queryset=Customer.objects.all(), required=False, allow_null=True)
    payment_method = serializers.ChoiceField(choices=Sale.Method.choices, default="CASH")
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")
    items = SaleLineInputSerializer(many=True, allow_empty=False)


class PaymentInputSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=Sale.Method.choices, default="CASH")
    note = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")


class PurchaseItemInputSerializer(serializers.Serializer):
    product = BusinessPKField(queryset=Product.objects.all())
    quantity = serializers.IntegerField(min_value=1)
    unit_cost = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"))


class PurchaseCreateSerializer(serializers.Serializer):
    supplier = BusinessPKField(queryset=Supplier.objects.all())
    paid_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False, default=Decimal("0"))
    note = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")
    items = PurchaseItemInputSerializer(many=True, allow_empty=False)


class PurchaseSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)

    class Meta:
        model = Purchase
        fields = ["id", "supplier", "supplier_name", "purchase_date", "total_amount", "paid_amount", "note"]


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "name"]


class ExpenseSerializer(serializers.ModelSerializer):
    category = BusinessPKField(queryset=ExpenseCategory.objects.all())
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Expense
        fields = ["id", "category", "category_name", "amount", "expense_date", "description", "payment_method"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value


class DemandForecastSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    algorithm = serializers.CharField(source="model_version.algorithm", read_only=True)

    class Meta:
        model = DemandForecast
        fields = ["id", "product", "product_name", "horizon_days", "predicted_demand", "current_stock", "days_of_cover",
                  "suggested_reorder", "status", "algorithm"]


class SalesForecastSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesForecast
        fields = ["forecast_date", "predicted_amount", "lower", "upper"]


class CustomerSegmentSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = CustomerSegment
        fields = ["customer", "customer_name", "recency_days", "frequency", "monetary", "r_score", "f_score", "m_score", "segment", "kmeans_cluster"]


class AnomalySerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="sale.invoice_number", read_only=True)
    label = serializers.SerializerMethodField()

    class Meta:
        model = AnomalyFlag
        fields = ["id", "sale", "invoice_number", "score", "reasons", "method", "reviewed", "label"]

    def get_label(self, obj):
        return "Potentially unusual transaction"


class AssociationSerializer(serializers.ModelSerializer):
    product_a_name = serializers.CharField(source="product_a.name", read_only=True)
    product_b_name = serializers.CharField(source="product_b.name", read_only=True)

    class Meta:
        model = ProductAssociation
        fields = ["product_a", "product_a_name", "product_b", "product_b_name", "pair_count", "support", "confidence", "lift"]
