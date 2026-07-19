"""
Field-level encryption for personally identifiable information (PII) at
rest — phone numbers, addresses, birthdays.

Important distinction from password storage: passwords are HASHED (one-way;
Django's PBKDF2 in accounts/models.py already does this correctly and this
module doesn't touch that). PII like an address needs to be readable again
by the app, so it's ENCRYPTED (two-way) instead — hashing an address would
make it permanently unrecoverable, which would break the app. "Encrypt what
must be read back, hash what must only ever be verified" is the guiding
rule; conflating the two is a common and dangerous mistake.

Uses Fernet (AES-128 in CBC mode with HMAC authentication) from the
`cryptography` package. The key lives in FIELD_ENCRYPTION_KEY (settings /
.env), never in source code.
"""
import datetime

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _fernet():
    key = settings.FIELD_ENCRYPTION_KEY
    if not key:
        raise ValueError(
            "FIELD_ENCRYPTION_KEY is not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
            "and put it in .env."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


class EncryptedCharField(models.CharField):
    """Transparently encrypts on write, decrypts on read. Behaves like a
    normal CharField everywhere else (forms, admin, serialization)."""

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ""):
            return value
        return _fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Data written before encryption was enabled, or wrong key.
            # Fail safe by surfacing an obviously-broken value rather than
            # crashing the whole page — but this should only ever happen
            # right after enabling encryption on a database with old
            # plaintext rows, which the migration path calls out.
            return "[unreadable — re-save this record]"


class EncryptedTextField(EncryptedCharField):
    def __init__(self, *args, **kwargs):
        kwargs.pop("max_length", None)
        super().__init__(*args, **kwargs)

    def db_type(self, connection):
        return "text"


class EncryptedDateField(models.DateField):
    """Stores dates encrypted as ISO strings, decrypts back to date objects."""

    def db_type(self, connection):
        return "text"

    def get_internal_type(self):
        # Deliberately NOT "DateField" — Django's DB backends (notably
        # SQLite) auto-convert DateField columns by trying to parse the
        # raw value as an ISO date, which mangles our encrypted ciphertext
        # into None before from_db_value below ever sees it. Reporting
        # "TextField" here skips that backend-level conversion; the actual
        # date parsing still happens correctly, just in from_db_value.
        return "TextField"

    def get_prep_value(self, value):
        if value in (None, ""):
            return value
        if isinstance(value, str):
            value = datetime.date.fromisoformat(value)
        return _fernet().encrypt(value.isoformat().encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return None
        try:
            decrypted = _fernet().decrypt(value.encode()).decode()
            return datetime.date.fromisoformat(decrypted)
        except InvalidToken:
            return None

    def to_python(self, value):
        if value is None or isinstance(value, datetime.date):
            return value
        try:
            return datetime.date.fromisoformat(value)
        except (ValueError, TypeError):
            return super().to_python(value)
