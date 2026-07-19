import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from store.models import Category, Product
from . import paymongo_client, paypal_client
from .models import Order, OrderItem

User = get_user_model()


class CheckoutAccessTests(TestCase):
    def test_checkout_requires_login(self):
        response = self.client.get(reverse("orders:checkout"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)


class OrderOwnershipTests(TestCase):
    """A01:2021 - Broken Access Control: users must only ever see their own orders."""

    def setUp(self):
        self.owner = User.objects.create_user(username="owner", email="o@example.com", password="OwnerPass123")
        self.intruder = User.objects.create_user(username="intruder", email="i@example.com", password="IntruderPass123")
        self.order = Order.objects.create(
            user=self.owner, full_name="Owner", address_line="1 St", city="Manila", postal_code="1000",
        )

    def test_owner_can_view_their_order(self):
        self.client.login(username="owner", password="OwnerPass123")
        response = self.client.get(reverse("orders:order_success", args=[self.order.id]))
        self.assertEqual(response.status_code, 200)

    def test_other_user_cannot_view_someone_elses_order(self):
        self.client.login(username="intruder", password="IntruderPass123")
        response = self.client.get(reverse("orders:order_success", args=[self.order.id]))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse("orders:order_success", args=[self.order.id]))
        self.assertEqual(response.status_code, 302)

    def test_pending_orders_display_as_order_placed(self):
        self.assertEqual(self.order.get_status_display(), "Order Placed")

    def test_order_history_only_shows_own_orders(self):
        Order.objects.create(user=self.intruder, full_name="Intruder", address_line="2 St", city="Cebu", postal_code="6000")
        self.client.login(username="owner", password="OwnerPass123")
        response = self.client.get(reverse("orders:order_history"))
        self.assertContains(response, "Order #" + str(self.order.id))
        self.assertNotContains(response, "Intruder")


class CheckoutPriceIntegrityTests(TestCase):
    """A04:2021 - Insecure Design: server always re-prices from the DB."""

    def setUp(self):
        self.user = User.objects.create_user(username="buyer", email="b@example.com", password="BuyerPass123")
        self.category = Category.objects.create(name="Office Supplies")
        self.product = Product.objects.create(name="Pen", category=self.category, price=Decimal("50.00"), stock=10)
        self.client.login(username="buyer", password="BuyerPass123")
        session = self.client.session
        session["cart"] = {str(self.product.id): {"quantity": 2}}
        session.save()

    @patch("orders.views.paymongo_client.create_checkout_session")
    def test_order_item_price_is_copied_from_database_at_checkout_paymongo(self, mock_create):
        mock_create.return_value = ("cs_test_123", "https://checkout.paymongo.com/test")

        response = self.client.post(reverse("orders:checkout"), {
            "full_name": "Buyer One", "address_line": "123 St", "city": "Manila", "postal_code": "1000",
            "payment_method": "paymongo", "selected_products": [str(self.product.id)],
        })
        self.assertEqual(response.status_code, 302)

        order = Order.objects.latest("created_at")
        item = order.items.get(product=self.product)
        # Price on the order line matches the DB price, never a client-supplied value.
        self.assertEqual(item.price, Decimal("50.00"))
        self.assertEqual(order.get_total_cost(), Decimal("100.00"))
        self.assertEqual(order.payment_provider, "paymongo")

        # Confirm what was actually sent to PayMongo used the real DB price too.
        sent_line_items = mock_create.call_args.args[1]
        self.assertEqual(sent_line_items[0]["amount_centavos"], 5000)  # PHP 50.00 -> 5000 centavos

    @patch("orders.views.paypal_client.create_order")
    def test_order_total_is_computed_from_database_at_checkout_paypal(self, mock_create):
        mock_create.return_value = ("PAYPAL-ORDER-1", "https://www.sandbox.paypal.com/checkoutnow?token=PAYPAL-ORDER-1")

        response = self.client.post(reverse("orders:checkout"), {
            "full_name": "Buyer One", "address_line": "123 St", "city": "Manila", "postal_code": "1000",
            "payment_method": "paypal", "selected_products": [str(self.product.id)],
        })
        self.assertEqual(response.status_code, 302)

        order = Order.objects.latest("created_at")
        self.assertEqual(order.payment_provider, "paypal")
        # Confirm the amount sent to PayPal was computed from the DB, not the client.
        sent_amount = mock_create.call_args.args[1]
        self.assertEqual(sent_amount, Decimal("100.00"))

    @patch("orders.views.paymongo_client.create_checkout_session")
    def test_insufficient_stock_blocks_order_creation(self, mock_create):
        self.product.stock = 1
        self.product.save()
        response = self.client.post(reverse("orders:checkout"), {
            "full_name": "Buyer One", "address_line": "123 St", "city": "Manila", "postal_code": "1000",
            "payment_method": "paymongo", "selected_products": [str(self.product.id)],
        })
        self.assertContains(response, "Not enough stock")
        mock_create.assert_not_called()
        self.assertFalse(Order.objects.filter(user=self.user).exists())


class OrderFulfillmentFlowTests(TestCase):
    """To Ship -> To Receive -> To Rate -> Completed."""

    def setUp(self):
        self.user = User.objects.create_user(username="buyer3", email="b3@example.com", password="BuyerPass123")
        self.other = User.objects.create_user(username="other3", email="o3@example.com", password="OtherPass123")
        self.order = Order.objects.create(
            user=self.user, full_name="Buyer", address_line="1 St", city="Manila", postal_code="1000",
            status=Order.Status.PAID,
        )

    def test_order_history_tabs_filter_correctly(self):
        shipped = Order.objects.create(
            user=self.user, full_name="Buyer", address_line="1 St", city="Manila", postal_code="1000",
            status=Order.Status.SHIPPED,
        )
        self.client.login(username="buyer3", password="BuyerPass123")

        r = self.client.get(reverse("orders:order_history"), {"tab": "to_ship"})
        self.assertContains(r, f"Order #{self.order.id}")
        self.assertNotContains(r, f"Order #{shipped.id}")

        r = self.client.get(reverse("orders:order_history"), {"tab": "to_receive"})
        self.assertContains(r, f"Order #{shipped.id}")
        self.assertNotContains(r, f"Order #{self.order.id}")

    def test_cannot_mark_received_before_shipped(self):
        self.client.login(username="buyer3", password="BuyerPass123")
        self.client.post(reverse("orders:mark_received", args=[self.order.id]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)  # unchanged

    def test_mark_received_moves_shipped_to_delivered(self):
        self.order.status = Order.Status.SHIPPED
        self.order.save()
        self.client.login(username="buyer3", password="BuyerPass123")
        self.client.post(reverse("orders:mark_received", args=[self.order.id]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DELIVERED)
        self.assertIsNotNone(self.order.delivered_at)

    def test_other_user_cannot_mark_received_on_someone_elses_order(self):
        self.order.status = Order.Status.SHIPPED
        self.order.save()
        self.client.login(username="other3", password="OtherPass123")
        response = self.client.post(reverse("orders:mark_received", args=[self.order.id]))
        self.assertEqual(response.status_code, 404)  # scoped to request.user, not just any order id
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SHIPPED)

    def test_rating_moves_order_to_completed(self):
        self.order.status = Order.Status.DELIVERED
        self.order.save()
        self.client.login(username="buyer3", password="BuyerPass123")
        response = self.client.post(reverse("orders:rate_order", args=[self.order.id]), {
            "rating": "5", "rating_comment": "Great!",
        })
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.COMPLETED)
        self.assertEqual(self.order.rating, 5)

    def test_cannot_rate_before_delivered(self):
        # status is still PAID from setUp
        self.client.login(username="buyer3", password="BuyerPass123")
        response = self.client.get(reverse("orders:rate_order", args=[self.order.id]))
        self.assertEqual(response.status_code, 302)  # redirected away, not allowed


class FieldEncryptionTests(TestCase):
    """A02:2021 - Cryptographic Failures: PII must not be stored as plaintext."""

    def test_user_pii_is_not_plaintext_in_the_database(self):
        user = User.objects.create_user(username="encrypttest", email="enc@example.com", password="EncPass123456")
        user.phone_number = "09171234567"
        user.address = "123 Rizal St, Tacloban City"
        user.save()

        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT phone_number, address FROM accounts_user WHERE id = %s", [user.id]
            )
            raw_phone, raw_address = cursor.fetchone()

        self.assertNotIn("09171234567", raw_phone)
        self.assertNotIn("Rizal St", raw_address)

        user.refresh_from_db()
        self.assertEqual(user.phone_number, "09171234567")
        self.assertEqual(user.address, "123 Rizal St, Tacloban City")

    def test_order_shipping_pii_is_not_plaintext_in_the_database(self):
        order = Order.objects.create(
            user=User.objects.create_user(username="enc2", email="enc2@example.com", password="EncPass123456"),
            full_name="Juan Dela Cruz", address_line="456 Mabini St", city="Cebu City", postal_code="6000",
        )
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT full_name, address_line FROM orders_order WHERE id = %s", [order.id])
            raw_name, raw_address = cursor.fetchone()

        self.assertNotIn("Juan Dela Cruz", raw_name)
        self.assertNotIn("Mabini", raw_address)
        order.refresh_from_db()
        self.assertEqual(order.full_name, "Juan Dela Cruz")


class VoucherAndVariationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="voucheruser", email="v@example.com", password="VoucherPass123")
        self.category = Category.objects.create(name="Electronics")
        self.product = Product.objects.create(
            name="T-Shirt", category=self.category, price=Decimal("100.00"), stock=10,
            variation_options="Small, Medium, Large",
        )
        self.client.login(username="voucheruser", password="VoucherPass123")

    def test_percent_voucher_applies_correct_discount(self):
        from orders.models import Voucher
        Voucher.objects.create(code="SAVE10", discount_type="percent", discount_value=Decimal("10"))

        session = self.client.session
        session["cart"] = {str(self.product.id): {"quantity": 2, "variation": "Medium", "voucher_code": "SAVE10"}}
        session.save()

        from cart.cart import Cart
        from django.test import RequestFactory
        request = RequestFactory().get("/")
        request.session = self.client.session
        cart = Cart(request)
        line = next(iter(cart))
        self.assertEqual(line["discount"], Decimal("20.00"))  # 10% of 200
        self.assertEqual(line["final_price"], Decimal("180.00"))
        self.assertEqual(line["variation"], "Medium")

    def test_expired_voucher_does_not_apply(self):
        from orders.models import Voucher
        from django.utils import timezone
        from datetime import timedelta
        Voucher.objects.create(
            code="OLDCODE", discount_type="percent", discount_value=Decimal("50"),
            expires_at=timezone.now() - timedelta(days=1),
        )
        session = self.client.session
        session["cart"] = {str(self.product.id): {"quantity": 1, "variation": "Small", "voucher_code": "OLDCODE"}}
        session.save()

        from cart.cart import Cart
        from django.test import RequestFactory
        request = RequestFactory().get("/")
        request.session = self.client.session
        cart = Cart(request)
        line = next(iter(cart))
        self.assertEqual(line["discount"], Decimal("0.00"))
        self.assertIsNotNone(line["voucher_error"])

    def test_voucher_scoped_to_other_product_does_not_apply(self):
        from orders.models import Voucher
        other_product = Product.objects.create(name="Mug", category=self.category, price=Decimal("50.00"), stock=5)
        Voucher.objects.create(code="MUGONLY", discount_type="fixed", discount_value=Decimal("5"), product=other_product)

        session = self.client.session
        session["cart"] = {str(self.product.id): {"quantity": 1, "variation": "Small", "voucher_code": "MUGONLY"}}
        session.save()

        from cart.cart import Cart
        from django.test import RequestFactory
        request = RequestFactory().get("/")
        request.session = self.client.session
        cart = Cart(request)
        line = next(iter(cart))
        self.assertEqual(line["discount"], Decimal("0.00"))
        self.assertIn("doesn't apply", line["voucher_error"])

    def test_apply_voucher_ajax_endpoint(self):
        from orders.models import Voucher
        Voucher.objects.create(code="FIVE", discount_type="fixed", discount_value=Decimal("5"))
        session = self.client.session
        session["cart"] = {str(self.product.id): {"quantity": 1, "variation": "Small", "voucher_code": ""}}
        session.save()

        response = self.client.post(
            reverse("cart:cart_apply_voucher", args=[self.product.id]), {"code": "five"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["discount"], "5.00")

    def test_order_item_snapshots_variation_and_voucher(self):
        from orders.models import Voucher
        Voucher.objects.create(code="TENOFF", discount_type="fixed", discount_value=Decimal("10"))
        session = self.client.session
        session["cart"] = {str(self.product.id): {"quantity": 1, "variation": "Large", "voucher_code": "TENOFF"}}
        session.save()

        with patch("orders.views.paymongo_client.create_checkout_session") as mock_create:
            mock_create.return_value = ("cs_x", "https://checkout.paymongo.com/x")
            self.client.post(reverse("orders:checkout"), {
                "full_name": "Buyer", "address_line": "1 St", "city": "Manila", "postal_code": "1000",
                "payment_method": "paymongo", "selected_products": [str(self.product.id)],
            })

        item = OrderItem.objects.latest("id")
        self.assertEqual(item.variation, "Large")
        self.assertEqual(item.voucher_code, "TENOFF")
        self.assertEqual(item.discount_amount, Decimal("10.00"))


class SelectiveCheckoutTests(TestCase):
    """Checkbox-based checkout: only the items the customer selects are
    ordered; everything else is left untouched in the cart."""

    def setUp(self):
        self.user = User.objects.create_user(username="selectiveuser", email="s@example.com", password="SelectPass123")
        self.category = Category.objects.create(name="Office Supplies")
        self.product_a = Product.objects.create(name="Pen", category=self.category, price=Decimal("10.00"), stock=5)
        self.product_b = Product.objects.create(name="Notebook", category=self.category, price=Decimal("20.00"), stock=5)
        self.client.login(username="selectiveuser", password="SelectPass123")
        session = self.client.session
        session["cart"] = {
            str(self.product_a.id): {"quantity": 1, "variation": "", "voucher_code": ""},
            str(self.product_b.id): {"quantity": 1, "variation": "", "voucher_code": ""},
        }
        session.save()

    def test_only_selected_item_becomes_an_order(self):
        with patch("orders.views.paymongo_client.create_checkout_session") as mock_create:
            mock_create.return_value = ("cs_x", "https://checkout.paymongo.com/x")
            self.client.post(reverse("orders:checkout"), {
                "full_name": "Buyer", "address_line": "1 St", "city": "Manila", "postal_code": "1000",
                "payment_method": "paymongo", "selected_products": [str(self.product_a.id)],
            })

        order = Order.objects.latest("created_at")
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().product, self.product_a)

    def test_unselected_item_remains_in_cart(self):
        with patch("orders.views.paymongo_client.create_checkout_session") as mock_create:
            mock_create.return_value = ("cs_x", "https://checkout.paymongo.com/x")
            self.client.post(reverse("orders:checkout"), {
                "full_name": "Buyer", "address_line": "1 St", "city": "Manila", "postal_code": "1000",
                "payment_method": "paymongo", "selected_products": [str(self.product_a.id)],
            })

        session = self.client.session
        cart_data = session.get("cart", {})
        self.assertNotIn(str(self.product_a.id), cart_data)
        self.assertIn(str(self.product_b.id), cart_data)

    def test_no_selection_shows_error_and_creates_no_order(self):
        response = self.client.post(reverse("orders:checkout"), {
            "full_name": "Buyer", "address_line": "1 St", "city": "Manila", "postal_code": "1000",
            "payment_method": "paymongo",
        })
        self.assertContains(response, "Select at least one item")
        self.assertFalse(Order.objects.filter(user=self.user).exists())


class CancelOrderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="cancelbuyer", email="c@example.com", password="CancelPass123")
        self.other = User.objects.create_user(username="cancelother", email="c2@example.com", password="OtherPass123")
        self.order = Order.objects.create(
            user=self.user, full_name="Buyer", address_line="1 St", city="Manila", postal_code="1000",
        )  # defaults to PENDING

    def test_can_cancel_pending_order(self):
        self.client.login(username="cancelbuyer", password="CancelPass123")
        response = self.client.post(reverse("orders:cancel_order", args=[self.order.id]))
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertIsNotNone(self.order.cancelled_at)

    def test_cannot_cancel_already_paid_order(self):
        self.order.status = Order.Status.PAID
        self.order.save()
        self.client.login(username="cancelbuyer", password="CancelPass123")
        response = self.client.post(reverse("orders:cancel_order", args=[self.order.id]), follow=True)
        self.assertContains(response, "can no longer be cancelled")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)

    def test_other_user_cannot_cancel_someone_elses_order(self):
        self.client.login(username="cancelother", password="OtherPass123")
        response = self.client.post(reverse("orders:cancel_order", args=[self.order.id]))
        self.assertEqual(response.status_code, 404)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)


class ContinueToPayTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="resumebuyer", email="r@example.com", password="ResumePass123")
        self.category = Category.objects.create(name="Office Supplies")
        self.product = Product.objects.create(name="Pen", category=self.category, price=Decimal("25.00"), stock=10)
        self.order = Order.objects.create(
            user=self.user, full_name="Buyer", address_line="1 St", city="Manila", postal_code="1000",
            payment_provider="paymongo",
        )
        OrderItem.objects.create(order=self.order, product=self.product, price=Decimal("25.00"), quantity=2)
        self.client.login(username="resumebuyer", password="ResumePass123")

    @patch("orders.views.paymongo_client.create_checkout_session")
    def test_continue_to_pay_creates_new_session_from_saved_items(self, mock_create):
        mock_create.return_value = ("cs_resume_1", "https://checkout.paymongo.com/resume")
        response = self.client.post(reverse("orders:continue_to_pay", args=[self.order.id]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://checkout.paymongo.com/resume")

        # Confirm it used the saved OrderItem price, not some client input.
        sent_line_items = mock_create.call_args.args[1]
        self.assertEqual(sent_line_items[0]["amount_centavos"], 2500)

        self.order.refresh_from_db()
        self.assertEqual(self.order.external_session_id, "cs_resume_1")

    def test_cannot_continue_to_pay_for_already_paid_order(self):
        self.order.status = Order.Status.PAID
        self.order.save()
        response = self.client.post(reverse("orders:continue_to_pay", args=[self.order.id]), follow=True)
        self.assertContains(response, "can no longer be paid")


class RequestRefundTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="refundbuyer", email="rf@example.com", password="RefundPass123")
        self.category = Category.objects.create(name="Office Supplies")
        self.product = Product.objects.create(name="Pen", category=self.category, price=Decimal("25.00"), stock=3)
        self.order = Order.objects.create(
            user=self.user, full_name="Buyer", address_line="1 St", city="Manila", postal_code="1000",
            status=Order.Status.PAID, payment_provider="paymongo", external_payment_id="pay_123",
        )
        OrderItem.objects.create(order=self.order, product=self.product, price=Decimal("25.00"), quantity=2)
        self.client.login(username="refundbuyer", password="RefundPass123")

    @patch("orders.views.paymongo_client.create_refund")
    def test_successful_refund_restocks_and_updates_status(self, mock_refund):
        mock_refund.return_value = ("ref_1", "succeeded")
        response = self.client.post(reverse("orders:request_refund", args=[self.order.id]), {"reason": "Changed my mind"})
        self.assertEqual(response.status_code, 302)

        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.REFUNDED)
        self.assertEqual(self.order.refund_id, "ref_1")
        self.assertEqual(self.order.refund_reason, "Changed my mind")
        self.assertEqual(self.product.stock, 5)  # 3 + 2 restocked

        # Confirm the refund amount sent was derived from the DB, not the client.
        sent_amount = mock_refund.call_args.args[1]
        self.assertEqual(sent_amount, 5000)  # PHP 25.00 x 2 -> 5000 centavos

    @patch("orders.views.paymongo_client.create_refund")
    def test_failed_refund_does_not_change_status_or_restock(self, mock_refund):
        mock_refund.return_value = ("ref_2", "failed")
        self.client.post(reverse("orders:request_refund", args=[self.order.id]))
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(self.product.stock, 3)

    def test_cannot_refund_pending_order(self):
        self.order.status = Order.Status.PENDING
        self.order.save()
        response = self.client.post(reverse("orders:request_refund", args=[self.order.id]), follow=True)
        self.assertContains(response, "eligible for a refund")

    @patch("orders.views.paypal_client.refund_capture")
    def test_paypal_refund_uses_capture_id(self, mock_refund):
        self.order.payment_provider = "paypal"
        self.order.external_payment_id = "CAPTURE-1"
        self.order.save()
        mock_refund.return_value = ("REFUND-1", "COMPLETED")
        response = self.client.post(reverse("orders:request_refund", args=[self.order.id]))
        self.assertEqual(response.status_code, 302)
        mock_refund.assert_called_once_with("CAPTURE-1")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.REFUNDED)


class DuplicatePaymentConfirmationTests(TestCase):
    """A webhook/callback retry for an already-paid order must not double
    deduct stock or double-count voucher usage."""

    def test_second_paymongo_confirmation_is_ignored(self):
        from orders.views import _mark_order_paid
        from orders.models import Voucher

        user = User.objects.create_user(username="dupuser", email="d@example.com", password="DupPass123456")
        category = Category.objects.create(name="Office Supplies")
        product = Product.objects.create(name="Pen", category=category, price=Decimal("10.00"), stock=10)
        voucher = Voucher.objects.create(code="ONCE", discount_type="fixed", discount_value=Decimal("1"))
        order = Order.objects.create(
            user=user, full_name="Buyer", address_line="1 St", city="Manila", postal_code="1000",
        )
        OrderItem.objects.create(
            order=order, product=product, price=Decimal("10.00"), quantity=1,
            voucher_code="ONCE", discount_amount=Decimal("1.00"),
        )

        _mark_order_paid(order, external_payment_id="pay_1")
        _mark_order_paid(order, external_payment_id="pay_2")  # simulated retry

        product.refresh_from_db()
        voucher.refresh_from_db()
        self.assertEqual(product.stock, 9)  # decremented once, not twice
        self.assertEqual(voucher.times_used, 1)  # counted once, not twice
        order.refresh_from_db()
        self.assertEqual(order.external_payment_id, "pay_1")  # first confirmation wins


class PayMongoWebhookSecurityTests(TestCase):
    """A08:2021 - Software & Data Integrity Failures: payment confirmation
    must only ever come from a signature-verified webhook, never from the
    browser redirect alone."""

    def setUp(self):
        self.user = User.objects.create_user(username="buyer2", email="b2@example.com", password="BuyerPass123")
        self.order = Order.objects.create(
            user=self.user, full_name="Buyer", address_line="1 St", city="Manila", postal_code="1000",
            payment_provider="paymongo", external_session_id="cs_test_abc",
        )

    def test_webhook_with_invalid_signature_is_rejected(self):
        response = self.client.post(
            reverse("orders:paymongo_webhook"),
            data=b'{"data": {"attributes": {"type": "checkout_session.payment.paid"}}}',
            content_type="application/json",
            HTTP_PAYMONGO_SIGNATURE="invalid_signature",
        )
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)

    def test_valid_webhook_marks_order_paid_and_decrements_stock(self):
        category = Category.objects.create(name="Office Supplies")
        product = Product.objects.create(name="Pen", category=category, price=Decimal("10.00"), stock=5)
        OrderItem.objects.create(order=self.order, product=product, price=Decimal("10.00"), quantity=2)

        body = json.dumps({
            "data": {
                "attributes": {
                    "type": "checkout_session.payment.paid",
                    "data": {
                        "id": "cs_test_abc",
                        "attributes": {"reference_number": str(self.order.id)},
                    },
                }
            }
        }).encode()

        from django.conf import settings

        with self.settings(PAYMONGO_WEBHOOK_SECRET="test-secret"):
            valid_signature = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
            response = self.client.post(
                reverse("orders:paymongo_webhook"),
                data=body,
                content_type="application/json",
                HTTP_PAYMONGO_SIGNATURE=valid_signature,
            )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        product.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(product.stock, 3)  # 5 - 2


class PayMongoSuccessPageReconciliationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="buyer5", email="b5@example.com", password="BuyerPass123")
        self.category = Category.objects.create(name="Office Supplies")
        self.product = Product.objects.create(name="Notebook", category=self.category, price=Decimal("20.00"), stock=6)
        self.order = Order.objects.create(
            user=self.user,
            full_name="Buyer",
            address_line="1 St",
            city="Manila",
            postal_code="1000",
            payment_provider="paymongo",
            external_session_id="cs_test_123",
        )
        OrderItem.objects.create(order=self.order, product=self.product, price=Decimal("20.00"), quantity=2)
        self.client.login(username="buyer5", password="BuyerPass123")

    @patch("orders.views.paymongo_client.get_checkout_session")
    def test_success_page_reconciles_pending_paymongo_order(self, mock_get_session):
        mock_get_session.return_value = {
            "id": "cs_test_123",
            "attributes": {
                "payment_intent": {"status": "succeeded"},
                "payments": [{"attributes": {"status": "paid"}}],
            },
        }

        response = self.client.get(reverse("orders:order_success", args=[self.order.id]))

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(self.order.external_payment_id, "cs_test_123")
        self.assertEqual(self.product.stock, 4)


class PayPalCaptureSecurityTests(TestCase):
    """PayPal has no signature-verified webhook in this integration — instead,
    payment is confirmed by a fresh server-to-server capture call made when
    the customer returns, never by the redirect parameters alone."""

    def setUp(self):
        self.user = User.objects.create_user(username="buyer4", email="b4@example.com", password="BuyerPass123")
        self.order = Order.objects.create(
            user=self.user, full_name="Buyer", address_line="1 St", city="Manila", postal_code="1000",
            payment_provider="paypal", external_session_id="PAYPAL-ORDER-1",
        )
        self.client.login(username="buyer4", password="BuyerPass123")

    def test_return_without_matching_token_does_not_mark_paid(self):
        response = self.client.get(
            reverse("orders:paypal_return", args=[self.order.id]), {"token": "WRONG-TOKEN"}
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)

    @patch("orders.views.paypal_client.capture_order")
    def test_return_with_matching_token_captures_and_marks_paid(self, mock_capture):
        mock_capture.return_value = ("COMPLETED", "CAPTURE-ID-1")
        response = self.client.get(
            reverse("orders:paypal_return", args=[self.order.id]), {"token": "PAYPAL-ORDER-1"}
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(self.order.external_payment_id, "CAPTURE-ID-1")

    @patch("orders.views.paypal_client.capture_order")
    def test_non_completed_capture_status_does_not_mark_paid(self, mock_capture):
        mock_capture.return_value = ("DECLINED", "")
        self.client.get(reverse("orders:paypal_return", args=[self.order.id]), {"token": "PAYPAL-ORDER-1"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)
