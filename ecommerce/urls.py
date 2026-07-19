from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),  # consider renaming this path in production (A05)
    path("accounts/", include("accounts.urls")),
    path("cart/", include("cart.urls")),
    path("orders/", include("orders.urls")),
    path("", include("store.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
