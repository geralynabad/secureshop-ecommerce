import hashlib
from io import BytesIO

from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageFont
from store.models import Category, Product, ProductVariant
from store.models import ProductImage


PRODUCT_COLORS = [
    (46, 49, 56),
    (76, 122, 99),
    (194, 139, 75),
    (101, 132, 173),
    (141, 148, 157),
    (115, 134, 106),
]


def _text_color(bg_rgb):
    brightness = (bg_rgb[0] * 299 + bg_rgb[1] * 587 + bg_rgb[2] * 114) / 1000
    return (255, 255, 255) if brightness < 160 else (31, 37, 34)


def _make_demo_image(label, subtitle, base_color, accent_color=None):
    size = (1200, 1200)
    image = Image.new("RGB", size, base_color)
    draw = ImageDraw.Draw(image)

    accent_color = accent_color or tuple(min(255, channel + 30) for channel in base_color)
    draw.rectangle([80, 80, 1120, 1120], outline=accent_color, width=18)
    draw.rounded_rectangle([170, 170, 1030, 1030], radius=80, fill=tuple(max(0, channel - 12) for channel in base_color))
    draw.ellipse([270, 250, 930, 910], outline=accent_color, width=24)
    draw.line([260, 910, 940, 250], fill=accent_color, width=18)

    title_color = _text_color(base_color)
    try:
        font_large = ImageFont.truetype("arial.ttf", 84)
        font_small = ImageFont.truetype("arial.ttf", 42)
    except Exception:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    title_box = draw.textbbox((0, 0), label, font=font_large)
    subtitle_box = draw.textbbox((0, 0), subtitle, font=font_small)
    draw.text(((size[0] - (title_box[2] - title_box[0])) / 2, 145), label, font=font_large, fill=title_color)
    draw.text(((size[0] - (subtitle_box[2] - subtitle_box[0])) / 2, 255), subtitle, font=font_small, fill=title_color)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return ContentFile(buffer.getvalue())


def _assign_image(field_file, filename, label, subtitle, base_color, accent_color=None):
    content = _make_demo_image(label, subtitle, base_color, accent_color)
    field_file.save(filename, content, save=False)


class Command(BaseCommand):
    help = (
        "Seeds the database with demo categories, products, and vouchers "
        "only — no accounts. Idempotent (safe to run repeatedly, including "
        "automatically on every deploy — see build.sh). For local/test "
        "demo accounts (admin login, security-scan test user), use "
        "`python manage.py seed_demo_accounts` instead — that one is "
        "deliberately NOT wired into the deploy process, since auto-creating "
        "an account with a known, publicly-documented password on a live "
        "site would be a real vulnerability, not just a convenience."
    )

    def handle(self, *args, **options):
        office, _ = Category.objects.get_or_create(name="Office Supplies")
        electronics, _ = Category.objects.get_or_create(name="Electronics")
        home_living, _ = Category.objects.get_or_create(name="Home & Living")
        health_beauty, _ = Category.objects.get_or_create(name="Health & Beauty")
        groceries, _ = Category.objects.get_or_create(name="Groceries")
        toys_games, _ = Category.objects.get_or_create(name="Toys & Games")
        fashion, _ = Category.objects.get_or_create(name="Fashion & Apparel")
        sports_outdoors, _ = Category.objects.get_or_create(name="Sports & Outdoors")
        books_stationery, _ = Category.objects.get_or_create(name="Books & Stationery")
        pet_supplies, _ = Category.objects.get_or_create(name="Pet Supplies")
        automotive, _ = Category.objects.get_or_create(name="Automotive")
        mobile_gadgets, _ = Category.objects.get_or_create(name="Mobile & Gadgets")

        demo_products = [
            {"name": "Ballpoint Pen (12-pack)", "category": office,
             "description": "Smooth-writing black ink pens, box of 12.", "price": 89.00, "stock": 150},
            {"name": "A4 Bond Paper Ream", "category": office,
             "description": "500 sheets, 70gsm, substance 20.", "price": 210.00, "stock": 80},
            {"name": "Stapler Heavy Duty", "category": office,
             "description": "Staples up to 50 sheets at once.", "price": 175.00, "stock": 30},
            {"name": "Wireless Mouse", "category": electronics,
             "description": "2.4GHz wireless optical mouse. Comes in three colors.", "price": 399.00, "stock": 40,
             "variation_options": "Black, White, Grey"},
            {"name": "USB-C Hub", "category": electronics,
             "description": "7-in-1 USB-C hub with HDMI and card reader.", "price": 899.00, "stock": 25},
            {"name": "Ceramic Dinner Plate Set (6-pc)", "category": home_living,
             "description": "Microwave and dishwasher safe, matte finish.", "price": 650.00, "stock": 20,
             "variation_options": "White, Cream"},
            {"name": "Cotton Bath Towel", "category": home_living,
             "description": "600 GSM soft-touch cotton bath towel.", "price": 320.00, "stock": 60,
             "variation_options": "Grey, Navy, Blush"},
            {"name": "Vitamin C 1000mg (60 Tablets)", "category": health_beauty,
             "description": "Immune support supplement, one tablet daily.", "price": 285.00, "stock": 100},
            {"name": "Facial Sunscreen SPF50", "category": health_beauty,
             "description": "Lightweight, non-greasy, matte finish sunscreen.", "price": 399.00, "stock": 70},
            {"name": "Brewed Coffee Beans (250g)", "category": groceries,
             "description": "Medium roast arabica beans from Benguet.", "price": 245.00, "stock": 45},
            {"name": "Extra Virgin Olive Oil (500ml)", "category": groceries,
             "description": "Cold-pressed, imported extra virgin olive oil.", "price": 410.00, "stock": 35},
            {"name": "Building Blocks Set (200-pc)", "category": toys_games,
             "description": "Compatible with major building-brick brands.", "price": 599.00, "stock": 25},
            {"name": "Board Game: Trivia Night", "category": toys_games,
             "description": "Family trivia board game, 4-8 players.", "price": 750.00, "stock": 15},
            {"name": "Cotton Crew T-Shirt", "category": fashion,
             "description": "100% cotton, pre-shrunk, everyday fit.", "price": 299.00, "stock": 90,
             "variation_options": "Small, Medium, Large, XL"},
            {"name": "Canvas Tote Bag", "category": fashion,
             "description": "Heavy-duty canvas, reinforced handles.", "price": 350.00, "stock": 50},
            {"name": "Yoga Mat (6mm)", "category": sports_outdoors,
             "description": "Non-slip, extra-cushioned yoga and exercise mat.", "price": 549.00, "stock": 30,
             "variation_options": "Purple, Teal, Black"},
            {"name": "Insulated Water Bottle (1L)", "category": sports_outdoors,
             "description": "Keeps drinks cold for 24 hours, leak-proof.", "price": 429.00, "stock": 55},
            {"name": "Bestselling Novel (Paperback)", "category": books_stationery,
             "description": "Award-winning contemporary fiction paperback.", "price": 450.00, "stock": 40},
            {"name": "Hardbound Notebook (A5)", "category": books_stationery,
             "description": "Dotted grid pages, ribbon bookmark, 200 pages.", "price": 195.00, "stock": 65},
            {"name": "Dry Dog Food (3kg)", "category": pet_supplies,
             "description": "Complete nutrition for adult dogs, chicken flavor.", "price": 780.00, "stock": 20},
            {"name": "Cat Litter (10L)", "category": pet_supplies,
             "description": "Clumping, low-dust, odor control cat litter.", "price": 399.00, "stock": 40},
            {"name": "Microfiber Car Wash Towel", "category": automotive,
             "description": "Scratch-free microfiber towel for car detailing.", "price": 199.00, "stock": 75},
            {"name": "Car Phone Mount", "category": automotive,
             "description": "Dashboard/windshield mount, one-hand operation.", "price": 289.00, "stock": 50},
            {"name": "Bluetooth Earbuds", "category": mobile_gadgets,
             "description": "True wireless earbuds with charging case.", "price": 1299.00, "stock": 30,
             "variation_options": "Black, White"},
            {"name": "Fast Charger (33W)", "category": mobile_gadgets,
             "description": "USB-C fast charger, compatible with most phones.", "price": 549.00, "stock": 60},
        ]
        created = 0
        for data in demo_products:
            product, was_created = Product.objects.get_or_create(name=data["name"], defaults=data)
            created += int(was_created)

            if not product.image:
                index = int(hashlib.sha1(product.name.encode("utf-8")).hexdigest()[:2], 16) % len(PRODUCT_COLORS)
                base_color = PRODUCT_COLORS[index]
                _assign_image(
                    product.image,
                    f"{product.slug or product.name.lower().replace(' ', '-')}-main.png",
                    product.name,
                    product.category.name,
                    base_color,
                )
                product.save(update_fields=["image"])

        variant_specs = [
            ("Wireless Mouse", [
                {"name": "Black", "color_hex": "#2E3138", "brief_description": "Matte black finish with a clean, understated look."},
                {"name": "White", "color_hex": "#F4F2EC", "brief_description": "Bright white shell for a lighter desk setup."},
                {"name": "Grey", "color_hex": "#8D949D", "brief_description": "Soft grey finish that blends into any workspace."},
            ]),
            ("Cotton Crew T-Shirt", [
                {"name": "Small", "color_hex": "#D8CBB8", "brief_description": "Close, everyday fit for a more tailored feel."},
                {"name": "Medium", "color_hex": "#B7A48B", "brief_description": "Balanced fit for relaxed daily wear."},
                {"name": "Large", "color_hex": "#8D7E6B", "brief_description": "Roomier cut with the same soft cotton feel."},
                {"name": "XL", "color_hex": "#5B5348", "brief_description": "Extra room without losing the clean silhouette."},
            ]),
            ("Bluetooth Earbuds", [
                {"name": "Black", "color_hex": "#22252B", "brief_description": "Low-profile black finish for a minimal look."},
                {"name": "White", "color_hex": "#F3F0EA", "brief_description": "Bright white finish that feels light and modern."},
            ]),
        ]

        for product_name, variants in variant_specs:
            product = Product.objects.filter(name=product_name).first()
            if not product:
                continue
            for order, variant_data in enumerate(variants):
                variant, _ = ProductVariant.objects.update_or_create(
                    product=product,
                    name=variant_data["name"],
                    defaults={
                        "color_hex": variant_data["color_hex"],
                        "brief_description": variant_data["brief_description"],
                        "sort_order": order,
                        "is_active": True,
                    },
                )

                if not variant.image:
                    _assign_image(
                        variant.image,
                        f"{product.slug or product.name.lower().replace(' ', '-')}-{variant.name.lower().replace(' ', '-')}.png",
                        variant.name,
                        product.name,
                        tuple(int(variant.color_hex[i:i+2], 16) for i in (1, 3, 5)) if variant.color_hex else PRODUCT_COLORS[order % len(PRODUCT_COLORS)],
                    )
                    variant.save(update_fields=["image"])

        gallery_specs = {
            "Wireless Mouse": ["Front angle", "Side angle", "Grip detail"],
            "Cotton Crew T-Shirt": ["Front view", "Folded view", "Fabric close-up"],
            "Bluetooth Earbuds": ["Case front", "Earbud profile", "Charging angle"],
        }

        for product_name, labels in gallery_specs.items():
            product = Product.objects.filter(name=product_name).first()
            if not product:
                continue
            existing = product.gallery_images.count()
            if existing >= len(labels):
                continue
            for offset, label in enumerate(labels):
                if product.gallery_images.filter(alt_text=label).exists():
                    continue
                image = ProductImage(product=product, alt_text=label, sort_order=offset)
                color = PRODUCT_COLORS[(offset + len(product_name)) % len(PRODUCT_COLORS)]
                _assign_image(
                    image.image,
                    f"{product.slug or product.name.lower().replace(' ', '-')}-{label.lower().replace(' ', '-')}.png",
                    product.name,
                    label,
                    color,
                )
                image.save()

        self.stdout.write(self.style.SUCCESS(f"Seed complete. {created} new products created."))

        from orders.models import Voucher
        mouse = Product.objects.filter(name="Wireless Mouse").first()
        voucher, voucher_created = Voucher.objects.get_or_create(
            code="WELCOME10",
            defaults={"discount_type": "percent", "discount_value": 10, "is_active": True},
        )
        fixed_voucher, fixed_created = Voucher.objects.get_or_create(
            code="MOUSE50OFF",
            defaults={"discount_type": "fixed", "discount_value": 50, "product": mouse, "is_active": True},
        )
        if voucher_created or fixed_created:
            self.stdout.write(self.style.SUCCESS(
                "Demo vouchers created: WELCOME10 (10% off any item), "
                "MOUSE50OFF (₱50 off Wireless Mouse only)."
            ))
