"""
Django settings for DinkUp — a pickleball league & tournament web app.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# For a class project this default is fine. Set DJANGO_SECRET_KEY if you put it online.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me-dinkup-pickleball-key")

# On Render, the RENDER environment variable is set automatically, so DEBUG turns off there.
ON_RENDER = "RENDER" in os.environ
DEBUG = os.environ.get("DJANGO_DEBUG", "0" if ON_RENDER else "1") == "1"

# "*" lets you open the site from your phone on the same Wi-Fi while testing.
ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = ["https://*.onrender.com"]
if ON_RENDER:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "leagues",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves CSS/JS on Render
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "dinkup_site.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "dinkup_site.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Chicago"  # Waco, TX
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise serves the CSS/JS when the site is online. If it isn't installed
# (e.g. an older local setup), the site still runs locally without it.
try:
    import whitenoise  # noqa: F401
except ImportError:
    MIDDLEWARE.remove("whitenoise.middleware.WhiteNoiseMiddleware")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "home"

# Keep players signed in on their phone for the whole league (about 60 days).
SESSION_COOKIE_AGE = 60 * 60 * 24 * 60

# --- AI assistant (optional) ---
# Without a key, the assistant uses built-in answers. Add ONE of these keys to switch to a real AI model.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "")  # optional override, e.g. "claude-haiku-5-5" or "gpt-4o-mini"
