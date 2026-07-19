from django.contrib.auth.models import AbstractUser
from django.db import models

from ecommerce.encryption import EncryptedCharField, EncryptedTextField, EncryptedDateField


class User(AbstractUser):
    """
    Custom user model (best practice: start every Django project with one,
    even if it only adds a couple of fields, so the schema can grow later
    without a painful migration).
    """

    class Gender(models.TextChoices):
        UNSPECIFIED = "unspecified", "Prefer not to say"
        FEMALE = "female", "Female"
        MALE = "male", "Male"
        OTHER = "other", "Other"

    # Email/username stay plaintext — both must remain queryable for login
    # and uniqueness checks, which reversible-but-searchable encryption
    # would need a more involved (deterministic/blind-index) scheme for.
    # Phone/address/birthday are true PII with no lookup requirement, so
    # they're encrypted at rest (see ecommerce/encryption.py).
    email = models.EmailField(unique=True)
    phone_number = EncryptedCharField(max_length=255, blank=True)
    address = EncryptedTextField(blank=True)
    gender = models.CharField(max_length=20, choices=Gender.choices, default=Gender.UNSPECIFIED, blank=True)
    birthday = EncryptedDateField(null=True, blank=True)
    avatar = models.ImageField(upload_to="avatars/%Y/%m/", blank=True, null=True)

    # Basic account-lockout support (A07:2021 - Identification &
    # Authentication Failures) — enforced in accounts/views.py.
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.username
