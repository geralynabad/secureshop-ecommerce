#!/usr/bin/env bash
# Exit on error — a failed step here should stop the deploy, not silently
# push a broken build live.
set -o errexit

pip install -r requirements.txt

# Collect static files into STATIC_ROOT for WhiteNoise to serve.
python manage.py collectstatic --no-input

# Apply any outstanding database migrations.
python manage.py migrate

# Render's free tier has no Shell access to run `createsuperuser`
# interactively, so this creates one non-interactively from environment
# variables instead — safe to leave in place permanently: on every deploy
# after the first, the username already exists and Django's createsuperuser
# exits with an error, which the `|| true` below swallows so it never
# breaks the build. Only runs at all if the three env vars are actually
# set, so it's a no-op with no DJANGO_SUPERUSER_* configured.
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_EMAIL" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    python manage.py createsuperuser --noinput || true
fi

# Optional demo catalog (products/categories/vouchers only — no accounts,
# see store/management/commands/seed_demo_data.py). Idempotent, but off by
# default on a real deploy — set SEED_DEMO_DATA=true in the Render
# dashboard if you want the sample catalog instead of building your own.
if [ "$SEED_DEMO_DATA" = "true" ]; then
    python manage.py seed_demo_data || true
fi
