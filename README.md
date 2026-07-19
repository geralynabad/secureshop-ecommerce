# SecureShop — Secure E-Commerce Platform (Django)

A Django-based online marketplace built for the "Developing a Secure E-commerce
Platform" project brief. It implements a working store (catalog, cart,
GCash/Maya/PayPal checkout, order history, admin) with security controls
mapped explicitly to the **OWASP Top 10 (2021)**.

## Stack
- **Django 6.0** (ORM, auth, templating, admin)
- **PayMongo Checkout Sessions** for GCash and Maya — no cards, per product requirements
- **PayPal Orders v2 API** as a second payment option
- **SQLite** for local dev, **PostgreSQL** in production (reads `DATABASE_URL` automatically if set — see "Deploying to Render" below)
- **python-decouple** for environment-based secrets
- **django-ratelimit** for login throttling
- **Pillow** for real image-content validation on uploads
- **WhiteNoise** for secure static file serving

## Quick start

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in SECRET_KEY, FIELD_ENCRYPTION_KEY, PayMongo, and PayPal keys
python manage.py migrate
python manage.py seed_demo_data       # 12 categories, 25 products, demo vouchers — no accounts
python manage.py seed_demo_accounts   # local/test-only admin + security-scan test user (see warning below)
python manage.py runserver
```

Visit `http://127.0.0.1:8000/`. Admin panel at `/admin/`
(username `admin`, password `AdminPass123!` — **change this immediately**,
it's a seeded demo credential only). `.env.example` ships with a working
example `FIELD_ENCRYPTION_KEY` so this runs out of the box — generate your
own before using this for anything real (instructions in that file).

**`seed_demo_accounts` is local/test-only and deliberately not part of the
deploy process** — it creates accounts with known, publicly-documented
passwords (right there in this README), which is fine on your own machine
but would be a real vulnerability on a live site. For your actual
production admin account, use `python manage.py createsuperuser`
(interactively) or the `DJANGO_SUPERUSER_*` environment variables described
in "Deploying to Render" below.

## Payment providers

Checkout offers two payment methods, chosen by the customer on the shipping
form — no card option exists anywhere in this app.

### GCash / Maya (via PayMongo)

1. Get test API keys from the [PayMongo Dashboard](https://dashboard.paymongo.com/developers) → Developers → API Keys.
2. Put them in `.env` as `PAYMONGO_PUBLIC_KEY` / `PAYMONGO_SECRET_KEY`.
3. In test mode, PayMongo's hosted checkout page has built-in test flows for GCash and Maya that don't require a real e-wallet account — follow the on-page prompts.
4. For the webhook (which is what actually marks an order "Paid" — see the A08 row below), register an endpoint in the PayMongo Dashboard pointing at `https://<your-domain>/orders/webhook/paymongo/`, or use their CLI/tunnel tooling for local testing, and put the signing secret in `.env` as `PAYMONGO_WEBHOOK_SECRET`.

### PayPal

1. Create a sandbox app at the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/applications/sandbox) to get a Client ID and Secret.
2. Put them in `.env` as `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`, and leave `PAYPAL_MODE=sandbox` for testing.
3. Log into [PayPal's sandbox test accounts](https://developer.paypal.com/dashboard/accounts) to get a test buyer account to pay with.
4. Unlike PayMongo, this integration doesn't use a webhook — when the customer returns from approving on PayPal's page, the app makes a fresh server-to-server **capture** call and trusts that response directly, since it's not just reading redirect parameters (see `orders/paypal_client.py`).

## OWASP Top 10 (2021) — how each risk is addressed

| # | Risk | Mitigation in this codebase |
|---|------|------------------------------|
| A01 | Broken Access Control | `@login_required` on all account/order views; `orders/views.py:order_success` checks `order.user_id == request.user.id` before showing an order; Django admin permission system gates `/admin/`; products can only be edited via admin/staff. |
| A02 | Cryptographic Failures | Secrets loaded from `.env` via `python-decouple`, never hardcoded (`settings.py`); passwords hashed with salted PBKDF2-SHA256 (Django default, pinned explicitly, one-way — never recoverable); PII (address, phone, birthday, shipping details) is separately **encrypted** at rest with Fernet/AES (`ecommerce/encryption.py`) since that data must be readable again by the app, unlike a password — see the "Data protection" section below for why hashing and encryption solve different problems; `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, and HSTS enforced when `DEBUG=False`; no payment credentials (GCash/Maya/PayPal login) ever touch this server — both providers handle that on their own hosted pages. |
| A03 | Injection (SQL, XSS) | All DB access goes through the Django ORM (parameterized queries) — no raw SQL anywhere (`store/views.py` search/filtering). Django templates auto-escape all output by default; no `\|safe` or `mark_safe()` is used on user input anywhere in the templates. A strict `Content-Security-Policy` header (`accounts/middleware.py`) is a second line of defense against XSS. |
| A04 | Insecure Design | Cart stores only `product_id` + `quantity` server-side in the session; **price is always re-read from the database at checkout**, so a tampered client can never set its own price (`orders/views.py:checkout`). Stock is re-validated at order time. |
| A05 | Security Misconfiguration | `DEBUG=False` by default in production config; `ALLOWED_HOSTS` required; security headers (`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, CSP) set centrally; `.env.example` documents required secrets without exposing real ones. |
| A06 | Vulnerable & Outdated Components | `requirements.txt` pins exact versions; documented process to run `pip list --outdated` / `pip-audit` before each release (see below). |
| A07 | Identification & Authentication Failures | Django's password validators enforce length/complexity (`AUTH_PASSWORD_VALIDATORS`); `django-ratelimit` throttles login attempts by IP (10/min); a custom per-account lockout (5 failed attempts → 15-minute lock) is layered on top (`accounts/views.py`); generic "invalid username or password" message prevents user enumeration. |
| A08 | Software & Data Integrity Failures | An order is only ever marked "paid" by a trustworthy server-side confirmation, never a browser redirect alone: PayMongo webhooks are cryptographically signature-verified (`orders/paymongo_client.py:verify_webhook_signature`) before being trusted; PayPal payments are confirmed by a fresh server-to-server **capture** API call made when the customer returns (`orders/views.py:paypal_return`), not by reading the redirect's query parameters. |
| A09 | Security Logging & Monitoring Failures | Dedicated `orders` and `accounts` loggers write to a rotating `logs/security.log` file, capturing failed logins, account lockouts, webhook signature failures, and payment confirmations. |
| A10 | Server-Side Request Forgery | No user-supplied URLs are ever fetched server-side; all outbound calls (PayMongo, PayPal) go to fixed, hardcoded API hosts. |

## Key security-relevant files

- `ecommerce/settings.py` — all hardening flags, password validators, logging
- `ecommerce/encryption.py` — Fernet field-level encryption for PII (see "Data protection" below)
- `accounts/middleware.py` — CSP + extra response headers
- `accounts/views.py` — rate limiting, account lockout, generic auth errors
- `store/forms.py` — real image-content validation (not just extension check)
- `cart/cart.py` — server-side session cart; price/discount never trusted from client
- `orders/vouchers.py` — single source of truth for voucher validation, used both by the AJAX apply endpoint and re-run again at checkout
- `orders/paymongo_client.py` — PayMongo checkout session creation + webhook signature verification
- `orders/paypal_client.py` — PayPal OAuth, order creation, and server-side capture
- `orders/views.py` — server-side re-pricing, ownership checks, selective checkout, payment confirmation for both providers (idempotent — a duplicate webhook/callback can't double-deduct stock or double-count voucher usage)

## Data protection: hashing vs. encryption

These solve two different problems and this app deliberately uses both:

- **Passwords are hashed** (PBKDF2-SHA256, Django's default) — one-way, never
  recoverable. The app only ever *verifies* a password, it never needs to
  read one back. This is unchanged from before.
- **PII is encrypted, not hashed** — a home address, phone number, or
  birthday must be readable again (to show on an order, ship a package,
  etc.), so it's encrypted with Fernet (AES-128 + HMAC) via
  `ecommerce/encryption.py` instead. Hashing this data would make it
  permanently unrecoverable and break the app. Encrypted fields: `User`
  address/phone/birthday, and `Order` full_name/address_line/city/postal_code.
  `email`/`username` stay plaintext since login and uniqueness checks need
  to query them directly — encrypting those would need a more involved
  (deterministic/blind-index) scheme this project doesn't implement.
- Generate your own `FIELD_ENCRYPTION_KEY` before using this for anything
  real (see `.env.example`) — losing or changing that key makes existing
  encrypted data permanently unreadable, so back up before rotating it.

## Shopping experience

- **Toast notifications** — adding to cart happens via a background request; a small toast confirms it without a full page reload (progressive enhancement: the same form still works as a normal POST if JavaScript is disabled).
- **Product variations** — a product can define options (e.g. "Black, White, Grey") in the admin; the customer must pick one before adding to cart, and it's snapshotted onto the order line so it survives later catalog changes.
- **Vouchers** — staff create voucher codes in the admin (percentage or fixed amount off, optionally scoped to one specific product, with expiry/usage limits). Customers apply a code per cart item; the discount shown is always re-validated server-side at checkout too, never trusted from the client (`orders/vouchers.py`).
- **Selective checkout** — the checkout page lists every cart item with its own checkbox (checked by default); only checked items become part of the order. Unchecked items stay in the cart for later.

## Customer account & order status features

- **Profile** (`/accounts/profile/`) — view and edit email, phone, address, gender, birthday, and a profile photo. Photo uploads go through the same real-image-content validation as product images (`store/forms.py:validate_product_image`), not just a filename/extension check.
- **Order status flow** — orders move through `To Pay → To Ship → To Receive → To Rate → Completed`:
  - `To Ship`: payment confirmed (PayMongo webhook or PayPal capture), awaiting fulfillment.
  - `To Receive`: staff marked it shipped (Django admin → Orders → select orders → "Mark selected orders as Shipped"). There's no real courier integration, so this step is manual.
  - `To Rate`: the customer clicks **"Order Received"** in their order history to confirm delivery themselves — the app doesn't guess this from a courier API.
  - `Completed`: the customer leaves a 1–5 star rating with an optional comment.
- **Order history tabs** (`/orders/history/?tab=...`) — `to_ship`, `to_receive`, `to_rate`, or omit `tab` for full purchase history.
- **Continue to Pay** — an unpaid ("To Pay") order can be resumed: a fresh PayMongo/PayPal payment session is created from the *already-saved* order lines (price/variation/discount were fixed at checkout time and are never recomputed here), using whichever provider was originally chosen.
- **Cancel Order** — only unpaid orders can be self-service cancelled. Once money has actually moved, cancellation isn't offered — that's a refund instead.
- **Request Refund** — available on any paid order (`To Ship` / `To Receive` / `To Rate` / `Completed`). This is a full, immediate refund via the original payment provider's API (`orders/paymongo_client.py:create_refund`, `orders/paypal_client.py:refund_capture`) — no manual staff approval step in this project, though a real store would likely want a review step before money moves automatically. A successful refund also restocks the product quantities. Refunding is idempotent with the rest of the payment logic — it only acts on orders in a refundable status.

## Catalog

Seeded via `seed_demo_data` (categories/products/vouchers) with **12 categories** and 25 sample products: Office Supplies, Electronics, Home & Living, Health & Beauty, Groceries, Toys & Games, Fashion & Apparel, Sports & Outdoors, Books & Stationery, Pet Supplies, Automotive, and Mobile & Gadgets.

## Automated tests

A 65-test Django unit test suite covers the security-relevant logic across
all four apps (password hashing, account lockout, XSS escaping, SQL
injection resistance, file-upload validation, order ownership, price
integrity, PayMongo webhook signature verification, PayPal capture
confirmation, order-status transitions, profile editing, field-level
encryption, voucher validation, selective checkout, order cancellation, resuming an unpaid order, and refunds:

```bash
python manage.py test
```

## Security testing artifacts

The `security_testing/` folder contains:
- **Security_Vulnerability_Report.docx** — full write-up of the vulnerability assessment, mapped to OWASP Top 10 (2021), with findings and remediation. Written against the original Stripe-based payment integration; the payment-provider swap to PayMongo/PayPal since then follows the same verified-server-side-confirmation pattern described in the A08 row above, but hasn't been re-scanned.
- **security_scan.py** — the automated test harness used to produce it (run against a live local instance with `python manage.py seed_demo_accounts` already applied, since the script logs in as `security_test_user`; OWASP ZAP itself wasn't installable in this offline build environment, so this script covers the same check categories: headers, cookies, CSRF, XSS, SQL injection, open redirects, authentication, and access control).
- **scan_results.txt** — raw output from that scan run (16/17 checks passed; the one finding is a dev-server-only header disclosure, addressed in the report).

`SecureShop_Presentation.pptx` in the project root summarizes the project, architecture, security design, and test results for presentation purposes (also describes the original Stripe integration — the slides haven't been updated for the PayMongo/PayPal swap).

## Deploying to Render

This project ships deploy-ready for [Render](https://render.com) (free tier, no credit card required): `render.yaml` defines the web service + a managed Postgres database together, `build.sh` runs migrations and collects static files on every deploy, and `settings.py` already reads `DATABASE_URL` (falling back to local SQLite when it's not set — nothing changes for local dev).

1. Push this project to a GitHub repository.
2. On [Render](https://dashboard.render.com/blueprints), click **New Blueprint Instance** and connect that repository. Render reads `render.yaml` automatically.
3. You'll be prompted for the environment variables that don't have a safe default:
   - `FIELD_ENCRYPTION_KEY` and your PayMongo/PayPal keys (see `.env.example` for where to get each)
   - `DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` — **Render's free tier has no Shell access**, so this is how your admin account actually gets created (`build.sh` runs `createsuperuser --noinput` from these on deploy; safe to leave set permanently — it's a no-op on every deploy after the first). Pick a real username/password here, not the local demo ones.
   - `SECRET_KEY` and `DATABASE_URL` are generated/wired automatically — no prompt for those.
4. Click **Apply**. First deploy takes a few minutes — watch the **Logs** tab.
5. Want the sample catalog (12 categories, 25 products, demo vouchers)? Set `SEED_DEMO_DATA=true` under your web service's **Environment** tab (off by default) and it'll populate on the next deploy. It's catalog-only — no accounts get created this way, unlike the local `seed_demo_accounts` command.

**Do not run `seed_demo_accounts` against a live Render deployment** — it creates an account with a password printed right there in this README, which is fine on your own machine and actively dangerous on a public site. Your real admin login comes from the `DJANGO_SUPERUSER_*` variables in step 3 instead.

**Two free-tier limitations worth knowing about before you rely on this:**
- Render's free Postgres database is deleted 30 days after creation (with a 14-day warning window to upgrade) — fine for a demo/capstone submission, not for anything long-lived without upgrading to a paid database.
- Render's free web service has an **ephemeral filesystem** — uploaded product images and profile photos will be lost on every redeploy or restart. For anything beyond a demo, point `DEFAULT_FILE_STORAGE` at an external object store (e.g. Cloudflare R2 or AWS S3 via `django-storages`) instead of local disk.

## Before deploying anywhere (Render or otherwise)

1. Set `DEBUG=False` and a real, unique `SECRET_KEY` (Render's blueprint generates `SECRET_KEY` for you; `DEBUG` defaults to `False` unless you explicitly set it).
2. Set `ALLOWED_HOSTS` to your real domain(s) — Render's own `.onrender.com` hostname is added automatically, no config needed for that part.
3. Put this behind HTTPS (already assumed by `SECURE_SSL_REDIRECT`/HSTS in `settings.py` — Render provides this automatically; a different host needs its own TLS termination, e.g. nginx + Let's Encrypt).
4. Use Postgres, not SQLite, for concurrent write safety (Render's blueprint does this for you).
5. Never run `seed_demo_accounts` against a real deployment — it's local/test-only by design (see above). Use `DJANGO_SUPERUSER_*` or interactive `createsuperuser` for your real admin account instead.
6. Run `pip install pip-audit && pip-audit` to check for known CVEs in dependencies.
7. Switch `PAYMONGO_SECRET_KEY`/`PAYMONGO_PUBLIC_KEY` to live keys and register the real webhook endpoint + secret in the PayMongo Dashboard.
8. Switch `PAYPAL_MODE=live` and use live PayPal Client ID/Secret from a verified business account.
9. Back up before rotating `FIELD_ENCRYPTION_KEY` — changing it makes existing encrypted data unreadable.
10. Consider adding 2FA (e.g. `django-otp`) for staff/admin accounts.
