from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import User


class RegisterForm(UserCreationForm):
    """
    Extends Django's built-in UserCreationForm, which already runs every
    validator in AUTH_PASSWORD_VALIDATORS and hashes the password with
    PBKDF2 before saving — never store or compare plaintext passwords.
    """
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ["username", "email", "phone_number", "password1", "password2"]

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class LoginForm(AuthenticationForm):
    """Thin wrapper kept separate so rate-limiting/lockout logic in the
    view has a single, predictable entry point."""
    pass


class ProfileEditForm(forms.ModelForm):
    """
    Deliberately excludes 'username' — allowing username changes creates
    extra edge cases (login history, display consistency) not worth the
    complexity here. Everything else here is safe to self-serve edit.
    """
    class Meta:
        model = User
        fields = ["email", "phone_number", "address", "gender", "birthday", "avatar"]
        widgets = {
            "birthday": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        # Exclude the current user's own row so re-saving your own
        # unchanged email doesn't falsely trigger the duplicate check.
        if User.objects.exclude(pk=self.instance.pk).filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        # Only run real-content validation on a newly uploaded file, not on
        # the existing stored avatar being passed through unchanged.
        if avatar and hasattr(avatar, "content_type"):
            from store.forms import validate_product_image
            validate_product_image(avatar)
        return avatar
