from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404
from .models import Product, Category


def product_list(request):
    products = Product.objects.filter(is_active=True).select_related("category")

    # Search / filtering — always via the Django ORM (parameterized under
    # the hood), NEVER via string-formatted raw SQL (A03: Injection).
    query = request.GET.get("q", "").strip()
    if query:
        products = products.filter(name__icontains=query)

    category_slug = request.GET.get("category")
    if category_slug:
        products = products.filter(category__slug=category_slug)

    paginator = Paginator(products, 12)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "store/product_list.html", {
        "page_obj": page_obj,
        "categories": Category.objects.all(),
        "query": query,
    })


def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    return render(request, "store/product_detail.html", {"product": product})
