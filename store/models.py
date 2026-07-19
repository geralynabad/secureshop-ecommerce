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
        return [v.strip() for v in self.variation_options.split(",") if v.strip()]

    def __str__(self):
        return self.name
