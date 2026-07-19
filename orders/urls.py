from django.urls import path
from . import views

app_name = "orders"

urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
    path("success/<int:order_id>/", views.order_success, name="order_success"),
    path("history/", views.order_history, name="order_history"),
    path("<int:order_id>/received/", views.mark_received, name="mark_received"),
    path("<int:order_id>/rate/", views.rate_order, name="rate_order"),
    path("<int:order_id>/cancel/", views.cancel_order, name="cancel_order"),
    path("<int:order_id>/continue-to-pay/", views.continue_to_pay, name="continue_to_pay"),
    path("<int:order_id>/refund/", views.request_refund, name="request_refund"),
    path("webhook/paymongo/", views.paymongo_webhook, name="paymongo_webhook"),
    path("paypal/<int:order_id>/return/", views.paypal_return, name="paypal_return"),
    path("paypal/<int:order_id>/cancel/", views.paypal_cancel, name="paypal_cancel"),
]
