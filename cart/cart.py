from decimal import Decimal

from store.models import Product

CART_SESSION_KEY = "cart"


class Cart:
    """
    Session-backed cart. Only product id, quantity, variation label, and an
    optional voucher *code* are stored in the session (server-side,
    signed); price and the actual discount amount are always re-derived
    from the database at read time (and again, independently, at
    checkout), so a tampered client can never set its own price or invent
    a discount (A08:2021 - Software & Data Integrity Failures).

    Simplification: cart lines are keyed by product id only, so adding the
    same product with a different variation replaces the stored variation
    rather than creating a second line. Fine for this project's scope; a
    true multi-variation cart would key lines by (product_id, variation).
    """

    def __init__(self, request):
        self.session = request.session
        cart = self.session.get(CART_SESSION_KEY)
        if cart is None:
            cart = self.session[CART_SESSION_KEY] = {}
        self.cart = cart

    def add(self, product, quantity=1, variation=""):
        product_id = str(product.id)
        quantity = max(1, min(int(quantity), product.stock or 0))
        if quantity == 0:
            return
        if product_id in self.cart:
            self.cart[product_id]["quantity"] = min(
                self.cart[product_id]["quantity"] + quantity, product.stock
            )
            if variation:
                self.cart[product_id]["variation"] = variation
        else:
            self.cart[product_id] = {"quantity": quantity, "variation": variation, "voucher_code": ""}
        self.save()

    def remove(self, product):
        self.remove_by_id(product.id)

    def remove_by_id(self, product_id):
        product_id = str(product_id)
        if product_id in self.cart:
            del self.cart[product_id]
            self.save()

    def set_voucher(self, product, code):
        product_id = str(product.id)
        if product_id in self.cart:
            self.cart[product_id]["voucher_code"] = (code or "").strip().upper()
            self.save()

    def remove_voucher(self, product):
        self.set_voucher(product, "")

    def save(self):
        self.session.modified = True

    def clear(self):
        self.session[CART_SESSION_KEY] = {}
        self.save()

    def __iter__(self):
        from orders.vouchers import validate_and_price  # local import avoids app-loading-order issues

        product_ids = self.cart.keys()
        products = Product.objects.filter(id__in=product_ids, is_active=True)
        products_map = {str(p.id): p for p in products}

        for product_id, item in self.cart.items():
            product = products_map.get(product_id)
            if not product:
                continue  # product removed/deactivated since being added

            quantity = item["quantity"]
            variation = item.get("variation", "")
            voucher_code = item.get("voucher_code", "")
            line_subtotal = product.price * quantity

            discount = Decimal("0.00")
            voucher_error = None
            if voucher_code:
                voucher, discount, voucher_error = validate_and_price(
                    voucher_code, product, quantity, product.price
                )

            yield {
                "product": product,
                "quantity": quantity,
                "variation": variation,
                "price": product.price,
                "voucher_code": voucher_code,
                "voucher_error": voucher_error,
                "discount": discount,
                "total_price": line_subtotal,
                "final_price": line_subtotal - discount,
            }

    def __len__(self):
        return sum(item["quantity"] for item in self.cart.values())

    def get_total_price(self):
        return sum((line["final_price"] for line in self), Decimal("0.00"))
