#!/usr/bin/env bash
# Exit on error — a failed step here should stop the deploy, not silently
# push a broken build live.
set -o errexit

pip install -r requirements.txt

# Collect static files into STATIC_ROOT for WhiteNoise to serve.
python manage.py collectstatic --no-input

# Apply any outstanding database migrations.
python manage.py migrate
