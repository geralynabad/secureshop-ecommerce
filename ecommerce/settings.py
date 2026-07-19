"""
Django settings for the secure e-commerce platform.

Security controls implemented here are mapped to OWASP Top 10 (2021) in README.md.
"""

from pathlib import Path

from cryptography.fernet import Fernet
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent
(BASE_DIR / "logs").mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Core / secrets  (A02:2021 - Cryptographic Failures: never hardcode secrets)
# ---------------------------------------------------------------------------
SECRET_KEY = config("SECRET_KEY", default="dev-only-insecure-key-change-me")

# Encrypts PII at rest (accounts/models.py address/phone/birthday, orders
# shipping fields) — see ecommerce/encryption.py for why this is encryption
# (reversible) rather than hashing (one-way, used only for passwords).
FIELD_ENCRYPTION_KEY = config(
    "FIELD_ENCRYPTION_KEY", default=Fernet.generate_key().decode()
)
DEBUG = config("DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost", cast=Csv())

# Render sets this automatically for every web service — no manual .env
# edit needed when deploying there. Other hosts (a custom domain, etc.)
# still go through ALLOWED_HOSTS above.
_render_hostname = config("RENDER_EXTERNAL_HOSTNAME", default="")
if _render_hostname:
    ALLOWED_HOSTS.append(_render_hostname)

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "store",
    "cart",
    "orders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",  # A01: CSRF protection on all POST/PUT/DELETE
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",  # blocks clickjacking
    "accounts.middleware.SecurityHeadersMiddleware",  # custom CSP / extra headers
]

ROOT_URLCONF = "ecommerce.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "cart.context_processors.cart",
            ],
        },
    },
]

WSGI_APPLICATION = "ecommerce.wsgi.application"

# ---------------------------------------------------------------------------
# Database — always accessed via Django ORM (parameterized queries).
# A03:2021 - Injection: never build raw SQL with string formatting.
# Reads DATABASE_URL if set (e.g. Render's managed Postgres connection
# string) and falls back to local SQLite otherwise — nothing to configure
# for local development, this only changes behavior in production.
# ---------------------------------------------------------------------------
import dj_database_url

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

# ---------------------------------------------------------------------------
# Password validation (A07:2021 - Identification & Authentication Failures)
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Django's default hasher is PBKDF2-SHA256 (salted, iterated) — do not replace
# with a weaker/faster hash. Listed explicitly so it can't be silently changed.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "store:product_list"
LOGOUT_REDIRECT_URL = "store:product_list"

# ---------------------------------------------------------------------------
# Session & cookie security (A02, A05: Security Misconfiguration)
# ---------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=not DEBUG, cast=bool)
SESSION_COOKIE_AGE = 60 * 60 * 2  # 2 hours
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=not DEBUG, cast=bool)

# ---------------------------------------------------------------------------
# Transport security — enforced only when DEBUG is False (prod)
# ---------------------------------------------------------------------------
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_CONTENT_TYPE_NOSNIFF = True  # X-Content-Type-Options: nosniff
X_FRAME_OPTIONS = "DENY"  # anti-clickjacking (A05)
SECURE_REFERRER_POLICY = "same-origin"

# ---------------------------------------------------------------------------
# Templates auto-escape all variables by default -> primary XSS defense
# (A03:2021 - Injection / Cross-Site Scripting). Never use `|safe` or
# `mark_safe()` on user-supplied content anywhere in this project.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# File upload validation (product images) — see store/forms.py
# ---------------------------------------------------------------------------
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# ---------------------------------------------------------------------------
# Static / media
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if not DEBUG
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        )
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Payment providers (A02: secrets pulled from environment, never hardcoded)
# ---------------------------------------------------------------------------
PAYMONGO_SECRET_KEY = config("PAYMONGO_SECRET_KEY", default="")
PAYMONGO_PUBLIC_KEY = config("PAYMONGO_PUBLIC_KEY", default="")
PAYMONGO_WEBHOOK_SECRET = config("PAYMONGO_WEBHOOK_SECRET", default="")

PAYPAL_CLIENT_ID = config("PAYPAL_CLIENT_ID", default="")
PAYPAL_CLIENT_SECRET = config("PAYPAL_CLIENT_SECRET", default="")
PAYPAL_MODE = config("PAYPAL_MODE", default="sandbox")  # "sandbox" or "live"

# ---------------------------------------------------------------------------
# Logging / monitoring (A09:2021 - Security Logging & Monitoring Failures)
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "security_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "security.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django.security": {"handlers": ["console", "security_file"], "level": "WARNING", "propagate": False},
        "orders": {"handlers": ["console", "security_file"], "level": "INFO", "propagate": False},
        "accounts": {"handlers": ["console", "security_file"], "level": "INFO", "propagate": False},
    },
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True
