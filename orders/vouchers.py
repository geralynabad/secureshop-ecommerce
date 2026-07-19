"""
Single source of truth for voucher validation, used by both the AJAX
"apply voucher" endpoint (cart page) and the checkout view. The checkout
view calls this again itself rather than trusting whatever discount the
client already displayed — a tampered request could otherwise claim any
discount amount it likes.
"""
from decimal import Decimal

from .models import Voucher


def validate_and_price(code, product, quantity, unit_price):
    """
    Returns (voucher_or_None, discount_amount, error_message_or_None).
    On any failure, voucher is None and discount_amount is 0 — the caller
    always gets a safe, non-discounted result rather than an exception.
    """
    code = (code or "").strip().upper()
    if not code:
        return None, Decimal("0.00"), None

    try:
        voucher = Voucher.objects.get(code=code)
    except Voucher.DoesNotExist:
        return None, Decimal("0.00"), "Voucher code not found."

    valid, error = voucher.is_valid_for(product)
    if not valid:
        return None, Decimal("0.00"), error

    discount = voucher.calculate_discount(unit_price, quantity)
    return voucher, discount, None
