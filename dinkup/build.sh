#!/usr/bin/env bash
# Render runs this when it builds the site.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
# Sample admin (demo / pickle123) and two sample leagues so the site isn't empty.
python manage.py load_demo
