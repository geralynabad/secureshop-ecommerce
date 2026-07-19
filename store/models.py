from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=110, unique=True, blank=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    stock = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to="products/%Y/%m/", blank=True, null=True)
    # Simple comma-separated variation list, e.g. "Red, Blue, Black" or
    # "Small, Medium, Large". Blank means the product has no variations.
    # This is deliberately lightweight (no separate variation-pricing or
    # per-variation stock model) — a single free-text option list snapshot
    # onto the order line at purchase time (OrderItem.variation).
    variation_options = models.CharField(
        max_length=255, blank=True,
        help_text="Comma-separated options, e.g. 'Red, Blue, Black'. Leave blank if this product has no variations.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["slug"]), models.Index(fields=["is_active"])]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("store:product_detail", kwargs={"slug": self.slug})

    def in_stock(self):
        return self.stock > 0

    def get_variation_list(self):
        variant_names = [variant.name for variant in self.get_active_variants()]
        if variant_names:
            return variant_names
        return [v.strip() for v in self.variation_options.split(",") if v.strip()]

    def get_active_variants(self):
        return self.variants.filter(is_active=True).order_by("sort_order", "name")

    def get_gallery_images(self):
        return self.gallery_images.all().order_by("sort_order", "id")

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    name = models.CharField(max_length=100)
    color_hex = models.CharField(max_length=7, blank=True, default="")
    brief_description = models.CharField(max_length=255, blank=True)
    image = models.ImageField(upload_to="products/variants/%Y/%m/", blank=True, null=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [models.UniqueConstraint(fields=["product", "name"], name="unique_product_variant_name")]

    def __str__(self):
        return f"{self.product.name} - {self.name}"


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="gallery_images")
    image = models.ImageField(upload_to="products/gallery/%Y/%m/")
    alt_text = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.product.name} gallery image"
