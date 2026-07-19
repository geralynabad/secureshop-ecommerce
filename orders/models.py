from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from ecommerce.encryption import EncryptedCharField
from store.models import Product


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Order Placed"
        PAID = "paid", "To Ship"
        SHIPPED = "shipped", "To Receive"
        DELIVERED = "delivered", "To Rate"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Payment failed"
        REFUNDED = "refunded", "Refunded"

    class PaymentProvider(models.TextChoices):
        PAYMONGO = "paymongo", "GCash / Maya (PayMongo)"
        PAYPAL = "paypal", "PayPal"

    # Orders that can still be paid for, cancelled, or refunded from "My Orders".
    CANCELLABLE_STATUSES = {Status.PENDING}
    REFUNDABLE_STATUSES = {Status.PAID, Status.SHIPPED, Status.DELIVERED, Status.COMPLETED}

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    # Snapshot of shipping details at time of order — never trust a client
    # to resend price/total; those are always computed server-side.
    # Encrypted at rest since this is PII (name + home address); no lookup
    # is ever needed on these fields, so encryption doesn't cost anything
    # functionally (see ecommerce/encryption.py).
    full_name = EncryptedCharField(max_length=255)
    address_line = EncryptedCharField(max_length=500)
    city = EncryptedCharField(max_length=255)
    postal_code = EncryptedCharField(max_length=100)

    # Generic fields so either gateway can be tracked the same way:
    # - external_session_id: PayMongo checkout session id, or PayPal order id
    # - external_payment_id: PayMongo payment id, or PayPal capture id
    payment_provider = models.CharField(max_length=20, choices=PaymentProvider.choices, blank=True, default="")
    external_session_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    external_payment_id = models.CharField(max_length=255, blank=True, default="")

    # Fulfillment tracking — shipped/delivered are advanced by staff in the
    # admin (no real courier integration here); "delivered" is confirmed by
    # the customer clicking "Order Received" in their order history.
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    # Cancellation (before payment) and refund (after payment) tracking.
    cancelled_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    refund_id = models.CharField(max_length=255, blank=True, default="")
    refund_reason = models.TextField(blank=True)

    # Customer rating, left once an order reaches "To Rate".
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    rating_comment = models.TextField(blank=True)
    rated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def get_subtotal(self):
        return sum((item.price * item.quantity for item in self.items.all()), Decimal("0.00"))

    def get_total_discount(self):
        return sum((item.discount_amount for item in self.items.all()), Decimal("0.00"))

    def get_total_cost(self):
        return self.get_subtotal() - self.get_total_discount()

    def __str__(self):
        return f"Order #{self.pk} ({self.user})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    # Price is copied at order time so later price changes never retroactively
    # alter a paid order (integrity + auditability). This is always the
    # *original* unit price — any voucher discount is tracked separately in
    # discount_amount so the receipt can show both.
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    quantity = models.PositiveIntegerField(default=1)

    # Snapshot of the selected variation (e.g. "Blue", "Large") at order
    # time — never a live FK to a variation option, so it survives even if
    # the product's variation list changes later.
    variation = models.CharField(max_length=100, blank=True)

    # Voucher applied to this specific line, re-validated server-side at
    # checkout (see orders/vouchers.py) — never trusted from client input.
    voucher_code = models.CharField(max_length=50, blank=True)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    def get_cost(self):
        return max(Decimal("0.00"), (self.price * self.quantity) - self.discount_amount)


class Voucher(models.Model):
    class DiscountType(models.TextChoices):
        PERCENT = "percent", "Percentage off"
        FIXED = "fixed", "Fixed amount off"

    code = models.CharField(max_length=50, unique=True, db_index=True)
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])

    # Null = valid for any product. Set = only valid for that specific product.
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True, related_name="vouchers")

    is_active = models.BooleanField(default=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True, help_text="Leave blank for unlimited uses.")
    times_used = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.code

    def is_valid_for(self, product):
        if not self.is_active:
            return False, "This voucher is no longer active."
        if self.expires_at and self.expires_at < timezone.now():
            return False, "This voucher has expired."
        if self.max_uses is not None and self.times_used >= self.max_uses:
            return False, "This voucher has reached its usage limit."
        if self.product_id is not None and self.product_id != product.id:
            return False, "This voucher doesn't apply to this item."
        return True, ""

    def calculate_discount(self, unit_price, quantity):
        line_total = unit_price * quantity
        if self.discount_type == self.DiscountType.PERCENT:
            discount = (line_total * self.discount_value) / Decimal("100")
        else:
            discount = self.discount_value * quantity
        discount = min(discount, line_total)  # never discount below zero
        return discount.quantize(Decimal("0.01"))
