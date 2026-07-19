from decimal import Decimal
from django.test import TestCase, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware

from store.models import Category, Product
from .cart import Cart


def _add_session(request):
    middleware = SessionMiddleware(lambda r: None)
    middleware.process_request(request)
    request.session.save()
    return request


class CartIntegrityTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.category = Category.objects.create(name="Office Supplies")
        self.product = Product.objects.create(name="Pen", category=self.category, price=Decimal("15.00"), stock=3)

    def _get_cart(self):
        request = _add_session(self.factory.get("/"))
        return Cart(request)

    def test_price_always_read_from_database_not_client(self):
        """
        The cart never stores a price in the session — only product_id and
        quantity. Even if a client tampered with the session, the total is
        recomputed from Product.price at read time, so a manipulated price
        can never reach checkout.
        """
        cart = self._get_cart()
        cart.add(self.product, quantity=2)
        line = list(cart)[0]
        self.assertEqual(line["price"], self.product.price)
        self.assertEqual(line["total_price"], Decimal("30.00"))
        # The underlying session dict has quantity/variation/voucher_code —
        # notably no price field, since price always comes from the DB.
        self.assertEqual(
            set(cart.cart[str(self.product.id)].keys()), {"quantity", "variation", "voucher_code"}
        )

    def test_quantity_cannot_exceed_available_stock(self):
        cart = self._get_cart()
        cart.add(self.product, quantity=999)
        line = list(cart)[0]
        self.assertEqual(line["quantity"], self.product.stock)

    def test_price_change_after_adding_to_cart_reflects_current_price(self):
        cart = self._get_cart()
        cart.add(self.product, quantity=1)
        self.product.price = Decimal("25.00")
        self.product.save()
        line = list(cart)[0]
        self.assertEqual(line["price"], Decimal("25.00"))

    def test_deactivated_product_disappears_from_cart_iteration(self):
        cart = self._get_cart()
        cart.add(self.product, quantity=1)
        self.product.is_active = False
        self.product.save()
        self.assertEqual(list(cart), [])
