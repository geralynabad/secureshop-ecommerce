from django.contrib import admin

from .forms import ProductForm
from .models import Category, Product, ProductImage, ProductVariant


class ProductVariantInline(admin.StackedInline):
    model = ProductVariant
    extra = 1
    fields = ("name", "color_hex", "brief_description", "image", "sort_order", "is_active")
    classes = ("collapse",)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductForm  # enforces image validation shown in store/forms.py
    inlines = [ProductVariantInline, ProductImageInline]
    list_display = ("name", "category", "price", "stock", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "description")
