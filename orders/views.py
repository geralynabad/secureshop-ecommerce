import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from django.db.models import F

from cart.cart import Cart
from . import paymongo_client, paypal_client
from .forms import ShippingForm, RatingForm
from .models import Order, OrderItem, Voucher

logger = logging.getLogger("orders")


def _create_order_from_cart(request, cart, shipping_data, selected_product_ids):
    """
    Re-validates stock, price, and voucher eligibility for every *selected*
    line from the DB right before creating the order — never trust cart
    totals blindly, since the session could theoretically be stale or
    tampered. Lines the customer left unchecked stay in the cart untouched.
    Returns (order, included_product_ids, error_message).
    """
    payment_method = shipping_data.pop("payment_method")
    matching_lines = [line for line in cart if str(line["product"].id) in selected_product_ids]

    if not matching_lines:
        return None, [], "Select at least one item to check out."

    order = Order.objects.create(user=request.user, payment_provider=payment_method, **shipping_data)
    included_ids = []

    for line in matching_lines:
        product = line["product"]
        if line["quantity"] > product.stock:
            order.delete()
            return None, [], f"Not enough stock for {product.name}."

        # Voucher discount is taken from this fresh iteration (which itself
        # re-validated against the DB just now) — a voucher that failed
        # validation simply doesn't get recorded, it doesn't block checkout.
        voucher_code = line["voucher_code"] if not line["voucher_error"] else ""
        discount = line["discount"] if not line["voucher_error"] else 0

        OrderItem.objects.create(
            order=order,
            product=product,
            price=product.price,
            quantity=line["quantity"],
            variation=line["variation"],
            voucher_code=voucher_code,
            discount_amount=discount,
        )
        included_ids.append(str(product.id))

    return order, included_ids, None


def _mark_order_paid(order, external_payment_id):
    """Shared by both payment providers — an order only ever becomes PAID
    here, never from a browser redirect alone (A08:2021 - Software & Data
    Integrity Failures). Idempotent: payment providers can and do retry
    webhook/callback delivery, so a second confirmation for an
    already-paid order must not double-deduct stock or double-count
    voucher usage."""
    if order.status != Order.Status.PENDING:
        logger.info("Order %s already in status=%s; ignoring duplicate payment confirmation.", order.id, order.status)
        return

    order.status = Order.Status.PAID
    order.external_payment_id = external_payment_id
    order.save(update_fields=["status", "external_payment_id"])

    for item in order.items.select_related("product"):
        product = item.product
        product.stock = max(0, product.stock - item.quantity)
        product.save(update_fields=["stock"])
        if item.voucher_code:
            Voucher.objects.filter(code=item.voucher_code).update(times_used=F("times_used") + 1)

    logger.info("Order %s marked PAID via %s.", order.id, order.payment_provider)


@login_required
def checkout(request):
    cart = Cart(request)
    if len(cart) == 0:
        return redirect("cart:cart_detail")

    if request.method == "POST":
        form = ShippingForm(request.POST)
        selected_product_ids = request.POST.getlist("selected_products")

        if form.is_valid():
            payment_method = form.cleaned_data["payment_method"]
            order, included_ids, error = _create_order_from_cart(
                request, cart, dict(form.cleaned_data), selected_product_ids
            )
            if error:
                form.add_error(None, error)
                return render(request, "orders/checkout.html", {"form": form, "cart": cart})

            success_url = request.build_absolute_uri(reverse("orders:order_success", args=[order.id]))
            cancel_url = request.build_absolute_uri(reverse("cart:cart_detail"))

            if payment_method == "paymongo":
                line_items = [
                    {
                        "name": item.product.name + (f" ({item.variation})" if item.variation else ""),
                        "amount_centavos": int((item.price * item.quantity - item.discount_amount) / item.quantity * 100),
                        "quantity": item.quantity,
                    }
                    for item in order.items.select_related("product")
                ]
                try:
                    session_id, checkout_url = paymongo_client.create_checkout_session(
                        order, line_items, success_url, cancel_url
                    )
                except paymongo_client.PayMongoError:
                    order.delete()
                    form.add_error(None, "Payment provider error. Please try again.")
                    return render(request, "orders/checkout.html", {"form": form, "cart": cart})

                order.external_session_id = session_id
                order.save(update_fields=["external_session_id"])
                for product_id in included_ids:
                    cart.remove_by_id(product_id)
                return redirect(checkout_url)

            else:  # paypal
                paypal_return_url = request.build_absolute_uri(
                    reverse("orders:paypal_return", args=[order.id])
                )
                paypal_cancel_url = request.build_absolute_uri(
                    reverse("orders:paypal_cancel", args=[order.id])
                )
                try:
                    paypal_order_id, approve_url = paypal_client.create_order(
                        order, order.get_total_cost(), paypal_return_url, paypal_cancel_url
                    )
                except paypal_client.PayPalError:
                    order.delete()
                    form.add_error(None, "Payment provider error. Please try again.")
                    return render(request, "orders/checkout.html", {"form": form, "cart": cart})

                order.external_session_id = paypal_order_id
                order.save(update_fields=["external_session_id"])
                for product_id in included_ids:
                    cart.remove_by_id(product_id)
                return redirect(approve_url)
    else:
        form = ShippingForm()

    return render(request, "orders/checkout.html", {"form": form, "cart": cart})


@login_required
def order_success(request, order_id):
    # Ownership check (A01: Broken Access Control) — a user may only ever
    # view their own order, regardless of what id is in the URL.
    order = get_object_or_404(Order, id=order_id)
    if order.user_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied

    if (
        order.status == Order.Status.PENDING
        and order.payment_provider == Order.PaymentProvider.PAYMONGO
        and order.external_session_id
    ):
        try:
            session = paymongo_client.get_checkout_session(order.external_session_id)
        except paymongo_client.PayMongoError:
            logger.info("Could not reconcile PayMongo order %s on success page.", order.id)
        else:
            session_attrs = session.get("attributes", {})
            payment_intent = session_attrs.get("payment_intent", {})
            payments = session_attrs.get("payments", [])
            payment_status = payment_intent.get("status", "")
            linked_payment_status = next((payment.get("attributes", {}).get("status", "") for payment in payments), "")

            if payment_status == "succeeded" or linked_payment_status == "paid":
                _mark_order_paid(order, external_payment_id=session.get("id", order.external_session_id))

    return render(request, "orders/order_success.html", {"order": order})


TAB_STATUS_MAP = {
    "to_ship": Order.Status.PAID,
    "to_receive": Order.Status.SHIPPED,
    "to_rate": Order.Status.DELIVERED,
}


@login_required
def order_history(request):
    tab = request.GET.get("tab", "all")
    orders = Order.objects.filter(user=request.user).prefetch_related("items__product")

    if tab in TAB_STATUS_MAP:
        orders = orders.filter(status=TAB_STATUS_MAP[tab])
    elif tab != "all":
        tab = "all"  # unknown ?tab= value silently falls back to "all"

    return render(request, "orders/order_history.html", {
        "orders": orders,
        "active_tab": tab,
        "refundable_statuses": [s.value for s in Order.REFUNDABLE_STATUSES],
    })


@login_required
@require_POST
def mark_received(request, order_id):
    """Customer-confirmed delivery. This is the only way an order moves
    from 'shipped' to 'delivered' — there's no courier webhook here, so we
    trust the customer's own confirmation rather than guessing."""
    order = get_object_or_404(Order, id=order_id, user=request.user)
    if order.status != Order.Status.SHIPPED:
        messages.error(request, "This order isn't out for delivery yet.")
        return redirect("orders:order_history")

    order.status = Order.Status.DELIVERED
    order.delivered_at = timezone.now()
    order.save(update_fields=["status", "delivered_at"])
    logger.info("Order %s marked delivered by customer confirmation.", order.id)
    messages.success(request, "Thanks for confirming! You can now rate this order.")
    return redirect("orders:order_history")


@login_required
@require_POST
def cancel_order(request, order_id):
    """Only unpaid orders can be self-service cancelled — once money has
    actually moved, that's a refund instead (see request_refund below),
    not a cancellation."""
    order = get_object_or_404(Order, id=order_id, user=request.user)
    if order.status not in Order.CANCELLABLE_STATUSES:
        messages.error(request, "This order can no longer be cancelled.")
        return redirect("orders:order_history")

    order.status = Order.Status.CANCELLED
    order.cancelled_at = timezone.now()
    order.save(update_fields=["status", "cancelled_at"])
    logger.info("Order %s cancelled by customer.", order.id)
    messages.success(request, "Order cancelled.")
    return redirect("orders:order_history")


@login_required
@require_POST
def continue_to_pay(request, order_id):
    """Resumes an abandoned/unpaid order — rebuilds a fresh payment session
    from the *already-saved* OrderItem rows (price/variation/discount were
    fixed at order creation time and are never recomputed here), using the
    same provider originally chosen at checkout."""
    order = get_object_or_404(Order, id=order_id, user=request.user)
    if order.status != Order.Status.PENDING:
        messages.error(request, "This order can no longer be paid for.")
        return redirect("orders:order_history")

    success_url = request.build_absolute_uri(reverse("orders:order_success", args=[order.id]))
    cancel_url = request.build_absolute_uri(reverse("cart:cart_detail"))

    if order.payment_provider == "paypal":
        paypal_return_url = request.build_absolute_uri(reverse("orders:paypal_return", args=[order.id]))
        paypal_cancel_url = request.build_absolute_uri(reverse("orders:paypal_cancel", args=[order.id]))
        try:
            paypal_order_id, approve_url = paypal_client.create_order(
                order, order.get_total_cost(), paypal_return_url, paypal_cancel_url
            )
        except paypal_client.PayPalError:
            messages.error(request, "Payment provider error. Please try again.")
            return redirect("orders:order_history")
        order.external_session_id = paypal_order_id
        order.save(update_fields=["external_session_id"])
        return redirect(approve_url)

    else:  # paymongo (or unset, treated as paymongo since that's checkout's default choice)
        line_items = [
            {
                "name": item.product.name + (f" ({item.variation})" if item.variation else ""),
                "amount_centavos": int((item.price * item.quantity - item.discount_amount) / item.quantity * 100),
                "quantity": item.quantity,
            }
            for item in order.items.select_related("product")
        ]
        try:
            session_id, checkout_url = paymongo_client.create_checkout_session(
                order, line_items, success_url, cancel_url
            )
        except paymongo_client.PayMongoError:
            messages.error(request, "Payment provider error. Please try again.")
            return redirect("orders:order_history")
        order.payment_provider = "paymongo"
        order.external_session_id = session_id
        order.save(update_fields=["payment_provider", "external_session_id"])
        return redirect(checkout_url)


@login_required
@require_POST
def request_refund(request, order_id):
    """
    Self-service, immediate refund — no manual staff approval step in this
    project. A real store would likely want a review step before money
    moves; this demonstrates the underlying provider integration cleanly
    instead. Always a full refund of the order's total; this project
    doesn't support partial refunds.
    """
    order = get_object_or_404(Order, id=order_id, user=request.user)
    if order.status not in Order.REFUNDABLE_STATUSES:
        messages.error(request, "This order isn't eligible for a refund.")
        return redirect("orders:order_history")

    if not order.external_payment_id:
        logger.error("Order %s has no external_payment_id; cannot refund.", order.id)
        messages.error(request, "This order can't be refunded automatically. Please contact support.")
        return redirect("orders:order_history")

    reason = request.POST.get("reason", "")[:255]

    try:
        if order.payment_provider == "paypal":
            refund_id, status = paypal_client.refund_capture(order.external_payment_id)
            succeeded = status == "COMPLETED"
        else:
            amount_centavos = int(order.get_total_cost() * 100)
            refund_id, status = paymongo_client.create_refund(
                order.external_payment_id, amount_centavos, notes=reason or "Customer requested refund"
            )
            succeeded = status in ("succeeded", "pending", "processing")  # all non-failed states accepted
    except (paymongo_client.PayMongoError, paypal_client.PayPalError):
        messages.error(request, "Refund could not be processed right now. Please try again later.")
        return redirect("orders:order_history")

    if not succeeded:
        logger.warning("Refund for order %s returned non-success status=%s", order.id, status)
        messages.error(request, "Refund could not be processed. Please contact support.")
        return redirect("orders:order_history")

    order.status = Order.Status.REFUNDED
    order.refunded_at = timezone.now()
    order.refund_id = refund_id
    order.refund_reason = reason
    order.save(update_fields=["status", "refunded_at", "refund_id", "refund_reason"])

    # Restock — the sale is being fully reversed.
    for item in order.items.select_related("product"):
        product = item.product
        product.stock = product.stock + item.quantity
        product.save(update_fields=["stock"])

    logger.info("Order %s refunded via %s (refund_id=%s).", order.id, order.payment_provider, refund_id)
    messages.success(request, "Refund processed.")
    return redirect("orders:order_history")


@login_required
def rate_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    if order.user_id != request.user.id:
        raise PermissionDenied
    if order.status not in (Order.Status.DELIVERED, Order.Status.COMPLETED):
        messages.error(request, "This order can't be rated yet.")
        return redirect("orders:order_history")

    if request.method == "POST":
        form = RatingForm(request.POST, instance=order)
        if form.is_valid():
            order = form.save(commit=False)
            order.status = Order.Status.COMPLETED
            order.rated_at = timezone.now()
            order.save()
            logger.info("Order %s rated %s stars.", order.id, order.rating)
            messages.success(request, "Thanks for your feedback!")
            return redirect("orders:order_history")
    else:
        form = RatingForm(instance=order)

    return render(request, "orders/rate_order.html", {"form": form, "order": order})


@csrf_exempt
@require_POST
def paymongo_webhook(request):
    """
    PayMongo webhooks are the source of truth for GCash/Maya payment
    confirmation — never mark an order paid purely because the browser was
    redirected to the success URL, since that URL can be visited without
    paying. Signature verification is what makes this endpoint trustworthy
    (A08:2021 - Software & Data Integrity Failures).
    """
    raw_body = request.body
    signature = request.META.get("HTTP_PAYMONGO_SIGNATURE", "")

    if not paymongo_client.verify_webhook_signature(raw_body, signature, settings.PAYMONGO_WEBHOOK_SECRET):
        logger.warning("Rejected PayMongo webhook with invalid signature.")
        return HttpResponseBadRequest("Invalid signature")

    try:
        payload = json.loads(raw_body)
        event_attrs = payload["data"]["attributes"]
        event_type = event_attrs["type"]
    except (ValueError, KeyError) as exc:
        logger.error("Malformed PayMongo webhook payload: %s", exc)
        return HttpResponseBadRequest("Malformed payload")

    if event_type == "checkout_session.payment.paid":
        session = event_attrs.get("data", {})
        session_id = session.get("id", "")
        reference_number = session.get("attributes", {}).get("reference_number", "")

        try:
            order = Order.objects.get(id=reference_number, external_session_id=session_id)
        except (Order.DoesNotExist, ValueError):
            logger.error(
                "PayMongo webhook for unknown order reference=%s session=%s", reference_number, session_id
            )
            return HttpResponse(status=200)

        _mark_order_paid(order, external_payment_id=session_id)

    return HttpResponse(status=200)


@login_required
def paypal_return(request, order_id):
    """
    The customer lands here after approving on PayPal's page. We don't
    trust this redirect by itself — we make a fresh server-to-server
    capture call, and that response is the actual confirmation.
    """
    order = get_object_or_404(Order, id=order_id, user=request.user)
    paypal_order_id = request.GET.get("token", "")

    if not paypal_order_id or paypal_order_id != order.external_session_id:
        messages.error(request, "Payment could not be verified.")
        return redirect("cart:cart_detail")

    try:
        status, capture_id = paypal_client.capture_order(paypal_order_id)
    except paypal_client.PayPalError:
        messages.error(request, "Payment provider error. Please try again.")
        return redirect("cart:cart_detail")

    if status == "COMPLETED":
        _mark_order_paid(order, external_payment_id=capture_id)
    else:
        logger.warning("PayPal capture for order %s returned status=%s", order.id, status)

    return redirect("orders:order_success", order_id=order.id)


@login_required
def paypal_cancel(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    if order.status == Order.Status.PENDING:
        order.status = Order.Status.FAILED
        order.save(update_fields=["status"])
    messages.info(request, "Payment was cancelled.")
    return redirect("cart:cart_detail")
