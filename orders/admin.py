from django.contrib import admin
from django.utils import timezone
from .models import Order, OrderItem, Voucher


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "price", "quantity", "variation", "voucher_code", "discount_amount")
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("id", "user__username", "user__email")
    readonly_fields = (
        "payment_provider", "external_session_id", "external_payment_id",
        "cancelled_at", "refunded_at", "refund_id",
        "created_at", "updated_at",
    )
    inlines = [OrderItemInline]
    actions = ["mark_as_shipped"]

    @admin.action(description="Mark selected orders as Shipped (To Receive)")
    def mark_as_shipped(self, request, queryset):
        # There's no real courier/logistics integration in this project —
        # staff advance an order from "To Ship" to "To Receive" manually
        # here once it's actually been handed off for delivery.
        updated = queryset.filter(status=Order.Status.PAID).update(
            status=Order.Status.SHIPPED, shipped_at=timezone.now()
        )
        self.message_user(request, f"{updated} order(s) marked as shipped.")


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ("code", "discount_type", "discount_value", "product", "is_active", "times_used", "max_uses", "expires_at")
    list_filter = ("discount_type", "is_active")
    search_fields = ("code",)
    readonly_fields = ("times_used",)

    def save_model(self, request, obj, form, change):
        obj.code = obj.code.strip().upper()
        super().save_model(request, obj, form, change)
