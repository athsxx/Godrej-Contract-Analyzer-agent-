"""Minimal Django settings for the standalone custom-dev scaffold.

This mirrors the directory structure of the main project but keeps only what is
needed to run the sample agent locally. All secrets come from environment
variables; do not hard-code credentials.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-custom-dev-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
# Include 0.0.0.0 so runserver 0.0.0.0:8000 matches the browser Host header; "*" does not cover that literal.
_extra_hosts = ["127.0.0.1", "localhost", "0.0.0.0"]
_host = os.environ.get("HOST", "").strip()
if _host:
    _extra_hosts.append(_host)
elif DEBUG:
    _extra_hosts.append("*")
ALLOWED_HOSTS: list[str] = _extra_hosts

# Entra ID (Microsoft) defaults for local testing – override via env in prod.
AZURE_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID")
AZURE_TENANT_ID = os.environ.get("AZURE_TENANT_ID")
AZURE_CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.microsoft",
    "guru",
]

SITE_ID = 1

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves /static/ from STATIC_ROOT when not using runserver (e.g. Gunicorn). Required for upload UI JS.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "guru.middleware.EnsureSiteMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "guru.middleware.RequireLoginMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "geg_guru.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "guru" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "geg_guru.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS: list[dict[str, str]] = []

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "guru" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# With DEBUG=True, serve static from app dirs without running collectstatic every time.
WHITENOISE_USE_FINDERS = DEBUG

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = _env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True

# HTTPS note: in production fronted by SSL; keep URLs/proxies HTTPS-aware.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = False  # Enable True when serving over HTTPS locally.
CSRF_COOKIE_SECURE = False     # Enable True when serving over HTTPS locally.

LOGIN_URL = "/accounts/microsoft/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"

ACCOUNT_AUTHENTICATION_METHOD = "username_email"
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_EMAIL_REQUIRED = False
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_ADAPTER = "guru.adapters.GuruSocialAccountAdapter"

SOCIALACCOUNT_PROVIDERS = {
    "microsoft": {
        "tenant": AZURE_TENANT_ID or "common",
        "scope": ["User.Read"],
        "OAUTH_PKCE_ENABLED": True,
        # "APP": {"client_id": AZURE_CLIENT_ID, "secret": AZURE_CLIENT_SECRET, "key": ""},
    }
}
try:
    SOCIALACCOUNT_REQUESTS_TIMEOUT = int(os.environ.get("SOCIALACCOUNT_REQUESTS_TIMEOUT", "10"))
except ValueError:
    SOCIALACCOUNT_REQUESTS_TIMEOUT = 10

ENFORCE_GLOBAL_LOGIN = _env_bool("ENFORCE_GLOBAL_LOGIN", False)

# Enforce POST token exchange for Microsoft (AADSTS900561 guard).
try:
    from allauth.socialaccount.providers.microsoft.views import MicrosoftGraphOAuth2Adapter
    from allauth.socialaccount.providers.oauth2 import client as _oauth2_client

    _tenant = AZURE_TENANT_ID or "common"
    _azure_base = f"https://login.microsoftonline.com/{_tenant}/oauth2/v2.0"
    MicrosoftGraphOAuth2Adapter.authorize_url = f"{_azure_base}/authorize"
    MicrosoftGraphOAuth2Adapter.access_token_url = f"{_azure_base}/token"
    MicrosoftGraphOAuth2Adapter.access_token_method = "POST"

    _orig_get_access_token_response = getattr(
        _oauth2_client.OAuth2Client,
        "_get_access_token_response",
        None,
    )

    if _orig_get_access_token_response is not None:
        def _ms_force_post(self, data, *args, **kwargs):
            url = (getattr(self, "access_token_url", "") or "").lower()
            if "login.microsoftonline.com" in url:
                self.access_token_method = "POST"
            return _orig_get_access_token_response(self, data, *args, **kwargs)

        _oauth2_client.OAuth2Client._get_access_token_response = _ms_force_post  # type: ignore[attr-defined]
except Exception:
    pass
