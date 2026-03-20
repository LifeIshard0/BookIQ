"""
bookiq/settings_production.py
==============================
Production settings for BookIQ deployed on Railway.

Inherits all defaults from settings.py, then overrides:
  - DEBUG = False
  - ALLOWED_HOSTS from environment variable
  - DATABASE_URL from Railway environment variable
  - STATIC_ROOT + WhiteNoise middleware
  - SECRET_KEY from environment variable (never hardcoded)
  - CORS restricted to production frontend
  - Secure cookie and HSTS settings

Usage:
  Set DJANGO_SETTINGS_MODULE=bookiq.settings_production
  in Railway environment variables.
"""

from bookiq.settings import *   # noqa: F401, F403 — inherit all dev settings
import os
import dj_database_url

# ─── Core ──────────────────────────────────────────────

DEBUG = False

SECRET_KEY = os.environ['DJANGO_SECRET_KEY']

ALLOWED_HOSTS = os.environ.get(
    'ALLOWED_HOSTS',
    'localhost'
).split(',')

# ─── Database ──────────────────────────────────────────
# Railway injects DATABASE_URL automatically when a
# PostgreSQL plugin is attached to the project.

DATABASES = {
    'default': dj_database_url.config(
        default=os.environ.get('DATABASE_URL'),
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# ─── Static files — WhiteNoise ─────────────────────────

STATIC_ROOT = BASE_DIR / 'staticfiles'

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Insert WhiteNoise immediately after SecurityMiddleware
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',       # ADD
] + [m for m in MIDDLEWARE if m != 'django.middleware.security.SecurityMiddleware']

# ─── Security ──────────────────────────────────────────

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# ─── CORS ──────────────────────────────────────────────
# Update ALLOWED_CORS_ORIGINS when you have a frontend URL.
# For now, leave open to allow Swagger UI and Postman testing.

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = os.environ.get(
    'CORS_ALLOWED_ORIGINS',
    ''
).split(',') if os.environ.get('CORS_ALLOWED_ORIGINS') else []

# Allow all origins if no CORS_ALLOWED_ORIGINS env var is set
# (safe for a pure API with no cookie auth)
if not CORS_ALLOWED_ORIGINS:
    CORS_ALLOW_ALL_ORIGINS = True

# ─── Logging ───────────────────────────────────────────
# Override dev logging — errors only to console (Railway captures stdout)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'production': {
            'format': '[{levelname}] {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'production',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'books': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'ERROR',
    },
}
