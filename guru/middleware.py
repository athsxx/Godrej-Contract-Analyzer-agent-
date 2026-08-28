"""Minimal auth middleware for the custom-dev scaffold."""

from __future__ import annotations

from typing import Callable

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.contrib.sites.models import Site
from django.http import HttpRequest, HttpResponse


class EnsureSiteMiddleware:
    """Ensure the configured SITE_ID row exists for django-allauth."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self._ensure_site_exists(request)
        return self.get_response(request)

    @staticmethod
    def _ensure_site_exists(request: HttpRequest) -> None:
        site_id = getattr(settings, "SITE_ID", 1)
        try:
            Site.objects.get(pk=site_id)
            return
        except Site.DoesNotExist:
            pass

        try:
            host = request.get_host()
        except Exception:
            host = ""
        host = (host or "").strip()
        if host.startswith("http://") or host.startswith("https://"):
            host = host.split("://", 1)[1]
        host = host or (settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else "localhost")
        host = host.strip() or "localhost"
        domain = host.lower()
        name = domain.split(":")[0] or domain

        Site.objects.update_or_create(
            pk=site_id,
            defaults={
                "domain": domain,
                "name": name,
            },
        )


class RequireLoginMiddleware:
    """Optionally enforce auth on non-public routes."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not getattr(settings, "ENFORCE_GLOBAL_LOGIN", False):
            return self.get_response(request)

        path = request.path or "/"
        if self._is_public_path(path):
            return self.get_response(request)

        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            return self.get_response(request)

        return redirect_to_login(path, login_url=getattr(settings, "LOGIN_URL", "/accounts/login/"))

    @staticmethod
    def _is_public_path(path: str) -> bool:
        normalized = path or "/"
        safe_prefixes = [
            "/static/",
            "/media/",
            "/.well-known/",
            "/favicon.ico",
            "/accounts/",
            "/admin/login",
            "/admin/logout",
            "/login/",
        ]
        if normalized == "/":
            return True
        return any(normalized.startswith(prefix) for prefix in safe_prefixes)
