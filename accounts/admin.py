from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "is_staff", "is_active", "failed_login_attempts")
    fieldsets = UserAdmin.fieldsets + (
        ("Profile", {"fields": ("phone_number", "address", "gender", "birthday", "avatar")}),
        ("Security", {"fields": ("failed_login_attempts", "locked_until")}),
    )
