"""
Thin wrapper around PayPal's Orders v2 API (server-side redirect flow, no
client-side JS SDK — consistent with the PayMongo hosted-checkout pattern
used elsewhere in this app).

Reference: https://developer.paypal.com/docs/api/orders/v2/
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger("orders")


class PayPalError(Exception):
    pass


def _api_base():
    return "https://api-m.paypal.com" if settings.PAYPAL_MODE == "live" else "https://api-m.sandbox.paypal.com"


def get_access_token():
    """
    Client-credentials OAuth token, required on every PayPal API call.
    Not cached here for simplicity — a low-traffic capstone project doesn't
    need token caching, but a production deployment should cache this for
    its ~9 hour lifetime rather than fetching a fresh token per request.
    """
    try:
        response = requests.post(
            f"{_api_base()}/v1/oauth2/token",
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("PayPal OAuth token request failed: %s", exc)
        raise PayPalError(str(exc)) from exc
    return response.json()["access_token"]


def create_order(order, total_amount, return_url, cancel_url):
    """Returns (paypal_order_id, approve_url)."""
    token = get_access_token()
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": str(order.id),
                "amount": {"currency_code": "PHP", "value": f"{total_amount:.2f}"},
            }
        ],
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED",
                    "user_action": "PAY_NOW",
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                }
            }
        },
    }
    try:
        response = requests.post(
            f"{_api_base()}/v2/checkout/orders",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("PayPal order creation failed for order %s: %s", order.id, exc)
        raise PayPalError(str(exc)) from exc

    data = response.json()
    approve_url = next((link["href"] for link in data["links"] if link["rel"] == "approve"), None)
    if not approve_url:
        raise PayPalError("PayPal response did not include an approval URL.")
    return data["id"], approve_url


def refund_capture(capture_id):
    """
    Reference: https://developer.paypal.com/docs/api/payments/v2/#captures_refund
    Full refund only (empty body) — this project doesn't support partial
    refunds. Returns (refund_id, status) where status is e.g. "COMPLETED".
    """
    token = get_access_token()
    try:
        response = requests.post(
            f"{_api_base()}/v2/payments/captures/{capture_id}/refund",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("PayPal refund failed for capture %s: %s", capture_id, exc)
        raise PayPalError(str(exc)) from exc

    data = response.json()
    return data.get("id", ""), data.get("status", "")


def capture_order(paypal_order_id):
    """
    Called when the customer returns from PayPal approval. This is a fresh
    server-to-server call whose response is the authoritative confirmation
    of payment — not the browser redirect itself, which could in principle
    be replayed or visited without ever approving anything.
    Returns (status, capture_id) where status is e.g. "COMPLETED".
    """
    token = get_access_token()
    try:
        response = requests.post(
            f"{_api_base()}/v2/checkout/orders/{paypal_order_id}/capture",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("PayPal capture failed for order %s: %s", paypal_order_id, exc)
        raise PayPalError(str(exc)) from exc

    data = response.json()
    status = data.get("status", "")
    capture_id = ""
    try:
        capture_id = data["purchase_units"][0]["payments"]["captures"][0]["id"]
    except (KeyError, IndexError):
        pass
    return status, capture_id
