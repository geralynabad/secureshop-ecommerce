"""
Thin wrapper around PayMongo's Checkout Sessions API (v2).

Reference: https://docs.paymongo.com/docs/payment-channels-hosted-checkout-quick-start
Only GCash and Maya are offered — no cards — per product requirements.
"""
import base64
import hashlib
import hmac
import logging

import requests
from django.conf import settings

logger = logging.getLogger("orders")

PAYMONGO_API_BASE = "https://api.paymongo.com/v2"


class PayMongoError(Exception):
    pass


def _auth_header():
    token = base64.b64encode(f"{settings.PAYMONGO_SECRET_KEY}:".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def create_checkout_session(order, line_items, success_url, cancel_url):
    """
    line_items: list of {"name": str, "amount_centavos": int, "quantity": int}
    Returns (checkout_session_id, checkout_url).
    """
    payload = {
        "data": {
            "attributes": {
                "line_items": [
                    {
                        "name": item["name"],
                        "amount": item["amount_centavos"],
                        "currency": "PHP",
                        "quantity": item["quantity"],
                    }
                    for item in line_items
                ],
                # No cards — GCash and Maya only, per product requirements.
                "payment_method_types": ["gcash", "paymaya"],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "reference_number": str(order.id),
            }
        }
    }

    try:
        response = requests.post(
            f"{PAYMONGO_API_BASE}/checkout_sessions",
            json=payload,
            headers=_auth_header(),
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("PayMongo checkout session creation failed for order %s: %s", order.id, exc)
        raise PayMongoError(str(exc)) from exc

    data = response.json()["data"]
    return data["id"], data["attributes"]["checkout_url"]


def get_checkout_session(session_id):
    """Retrieve a checkout session with secret-key access.

    The returned payload includes the session attributes and, when available,
    the linked payment intent / payment records.
    """
    try:
        response = requests.get(
            f"{PAYMONGO_API_BASE}/checkout_sessions/{session_id}",
            headers=_auth_header(),
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("PayMongo checkout session retrieval failed for %s: %s", session_id, exc)
        raise PayMongoError(str(exc)) from exc

    return response.json()["data"]


def create_refund(payment_id, amount_centavos, reason="requested_by_customer", notes=""):
    """
    Reference: https://developers.paymongo.com/reference/create-a-refund
    Refunds are a separate (v1) resource from Checkout Sessions (v2) in
    PayMongo's API. Returns (refund_id, status) where status is one of
    pending/processing/succeeded/failed.
    """
    payload = {
        "data": {
            "attributes": {
                "amount": amount_centavos,
                "payment_id": payment_id,
                "reason": reason,
                "notes": notes[:255],
            }
        }
    }
    try:
        response = requests.post(
            "https://api.paymongo.com/v1/refunds",
            json=payload,
            headers=_auth_header(),
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("PayMongo refund failed for payment %s: %s", payment_id, exc)
        raise PayMongoError(str(exc)) from exc

    data = response.json()["data"]
    return data["id"], data["attributes"]["status"]


def verify_webhook_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    """
    PayMongo signs webhooks with HMAC-SHA256 over the raw request body.
    Always verify BEFORE parsing the body — an unverified endpoint will
    process any request sent to it (see PayMongo's security best practices).
    """
    if not signature_header or not secret:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
