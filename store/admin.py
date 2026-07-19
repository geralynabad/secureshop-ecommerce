from django.contrib import admin
from .models import Category, Product
from .forms import ProductForm


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductForm  # enforces image validation shown in store/forms.py
    list_display = ("name", "category", "price", "stock", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "description")
