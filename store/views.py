from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404
from .models import Product, Category


COLOR_PALETTE = ["#2E3138", "#6E7D8C", "#B36B4C", "#C49A5A", "#7D8F6A", "#9D6B8B", "#3F6A77", "#D6C7B8"]


def _palette_color(name, index):
    if not name:
        return COLOR_PALETTE[index % len(COLOR_PALETTE)]
    normalized = name.lower()
    if "white" in normalized or "cream" in normalized or "ivory" in normalized:
        return "#F4F1EA"
    if "black" in normalized or "charcoal" in normalized:
        return "#2B2F36"
    if "grey" in normalized or "gray" in normalized or "stone" in normalized:
        return "#8E97A1"
    if "blue" in normalized or "navy" in normalized or "teal" in normalized:
        return "#4E7A8B"
    if "green" in normalized or "sage" in normalized or "olive" in normalized:
        return "#73866A"
    if "pink" in normalized or "rose" in normalized or "blush" in normalized:
        return "#C98F95"
    if "brown" in normalized or "tan" in normalized or "sand" in normalized:
        return "#A98763"
    return COLOR_PALETTE[index % len(COLOR_PALETTE)]


def _brief_variant_description(name, product_description):
    if not name:
        return product_description
    return f"{name} finish with a clean, polished look. {product_description[:90].rstrip()}"


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

    if not variants:
        fallback_options = product.get_variation_list()
        variants = [
            type("VariantPreview", (), {
                "name": option,
                "brief_description": _brief_variant_description(option, product.description),
                "color_hex": _palette_color(option, index),
                "image": None,
            })()
            for index, option in enumerate(fallback_options)
        ]

    default_variant = variants[0] if variants else None
    selected_description = default_variant.brief_description if default_variant and default_variant.brief_description else product.description

    hero_image = None
    if gallery_items:
        hero_image = gallery_items[0]
    elif default_variant and getattr(default_variant, "image", None):
        hero_image = {"url": default_variant.image.url, "alt": default_variant.name}

    if not gallery_items and product.image:
        gallery_items = [
            {"url": product.image.url, "alt": f"{product.name} front view", "placeholder": False},
            {"url": product.image.url, "alt": f"{product.name} angle view", "placeholder": False},
            {"url": product.image.url, "alt": f"{product.name} detail view", "placeholder": False},
        ]
    elif not gallery_items:
        gallery_items = [
            {"placeholder": True, "label": "Front angle"},
            {"placeholder": True, "label": "Side angle"},
            {"placeholder": True, "label": "Detail angle"},
        ]

    if not hero_image:
        hero_image = gallery_items[0]

    return render(request, "store/product_detail.html", {
        "product": product,
        "variants": variants,
        "gallery_items": gallery_items,
        "hero_image": hero_image,
        "default_variant": default_variant,
        "selected_description": selected_description,
    })
