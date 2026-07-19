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
    product = get_object_or_404(
        Product.objects.prefetch_related("variants", "gallery_images"),
        slug=slug,
        is_active=True,
    )

    variants = list(product.get_active_variants())
    gallery_items = []

    if product.image:
        gallery_items.append({"url": product.image.url, "alt": product.name})

    for image in product.get_gallery_images():
        gallery_items.append({"url": image.image.url, "alt": image.alt_text or product.name})

    default_variant = variants[0] if variants else None
    selected_description = default_variant.brief_description if default_variant and default_variant.brief_description else product.description

    hero_image = None
    if gallery_items:
        hero_image = gallery_items[0]
    elif default_variant and default_variant.image:
        hero_image = {"url": default_variant.image.url, "alt": default_variant.name}

    return render(request, "store/product_detail.html", {
        "product": product,
        "variants": variants,
        "gallery_items": gallery_items,
        "hero_image": hero_image,
        "default_variant": default_variant,
        "selected_description": selected_description,
    })
