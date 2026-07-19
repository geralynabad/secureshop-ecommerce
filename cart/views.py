from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from store.models import Product
from .cart import Cart


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


@require_POST  # state-changing action must be POST, protected by CSRF middleware
def cart_add(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id, is_active=True)
    quantity = request.POST.get("quantity", 1)
    variation = request.POST.get("variation", "")
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = 1

    # If the product defines variations, require a real selection rather
    # than silently defaulting to "no variation".
    if product.get_variation_list() and variation not in product.get_variation_list():
        message = "Please choose an option before adding to cart."
        if _is_ajax(request):
            return JsonResponse({"success": False, "message": message}, status=400)
        messages.error(request, message)
        return redirect(product.get_absolute_url())

    cart.add(product=product, quantity=quantity, variation=variation)
    message = f"Added {product.name} to your cart."

    if _is_ajax(request):
        return JsonResponse({"success": True, "message": message, "cart_count": len(cart)})

    messages.success(request, message)
    return redirect("cart:cart_detail")


@require_POST
def cart_remove(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    cart.remove(product)
    if _is_ajax(request):
        return JsonResponse({"success": True, "cart_count": len(cart)})
    messages.info(request, f"Removed {product.name} from your cart.")
    return redirect("cart:cart_detail")


@require_POST
def cart_apply_voucher(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    code = request.POST.get("code", "")
    cart.set_voucher(product, code)

    # Re-read the freshly-set line back out of the cart so the response
    # reflects the same validation the cart itself will apply.
    line = next((line for line in cart if line["product"].id == product.id), None)
    if line is None:
        return JsonResponse({"success": False, "message": "Item not found in cart."}, status=404)

    if line["voucher_error"]:
        return JsonResponse({
            "success": False,
            "message": line["voucher_error"],
            "final_price": str(line["total_price"]),
            "discount": "0.00",
        })

    return JsonResponse({
        "success": True,
        "message": f"Voucher applied: -₱{line['discount']}",
        "final_price": str(line["final_price"]),
        "discount": str(line["discount"]),
        "cart_total": str(cart.get_total_price()),
    })


def cart_detail(request):
    cart = Cart(request)
    return render(request, "cart/cart_detail.html", {"cart": cart})
