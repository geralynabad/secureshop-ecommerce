from django import forms
from django.core.exceptions import ValidationError
from PIL import Image
from .models import Product

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024  # 5MB


def validate_product_image(image_file):
    """
    Defends against malicious file upload (A05/A04): checks declared
    content-type, size, AND re-decodes the file with Pillow to confirm it
    is a genuine, well-formed image rather than a renamed script or a
    polyglot file. Never trust a client-supplied extension alone.
    """
    if image_file.size > MAX_UPLOAD_SIZE_BYTES:
        raise ValidationError("Image file is too large (max 5MB).")

    content_type = getattr(image_file, "content_type", None)
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationError("Unsupported image type. Use JPEG, PNG, or WebP.")

    try:
        img = Image.open(image_file)
        img.verify()
    except Exception:
        raise ValidationError("The uploaded file is not a valid image.")
    finally:
        image_file.seek(0)


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["category", "name", "description", "price", "stock", "image", "variation_options", "is_active"]

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image:
            validate_product_image(image)
        return image
