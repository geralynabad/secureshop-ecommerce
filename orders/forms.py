from django import forms
from .models import Order


class ShippingForm(forms.Form):
    PAYMENT_CHOICES = [
        ("paymongo", "GCash / Maya"),
        ("paypal", "PayPal"),
    ]

    full_name = forms.CharField(max_length=200)
    address_line = forms.CharField(max_length=255)
    city = forms.CharField(max_length=100)
    postal_code = forms.CharField(max_length=20)
    payment_method = forms.ChoiceField(choices=PAYMENT_CHOICES, widget=forms.RadioSelect)

    def clean_full_name(self):
        return self.cleaned_data["full_name"].strip()


class RatingForm(forms.ModelForm):
    rating = forms.ChoiceField(
        choices=[(i, i) for i in range(5, 0, -1)],
        widget=forms.RadioSelect,
    )

    class Meta:
        model = Order
        fields = ["rating", "rating_comment"]
        widgets = {
            "rating_comment": forms.Textarea(attrs={"rows": 3, "placeholder": "Optional: tell us more"}),
        }
        labels = {"rating_comment": "Comment"}
