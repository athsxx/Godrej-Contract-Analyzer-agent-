"""Custom allauth adapter for Microsoft OAuth in the custom-dev scaffold."""

from __future__ import annotations

from typing import Any

import logging

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned

logger = logging.getLogger("__allauth_debug__")


def _extract_email(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("email", "mail", "userPrincipalName", "preferred_username", "upn"):
        raw = data.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    return ""


def _extract_names(data: dict[str, Any] | None) -> tuple[str, str, str]:
    if not isinstance(data, dict):
        return "", "", ""
    given = (data.get("given_name") or data.get("givenName") or data.get("first_name") or "").strip()
    family = (data.get("family_name") or data.get("surname") or data.get("last_name") or "").strip()
    display = (data.get("name") or data.get("displayName") or data.get("preferred_username") or "").strip()
    return given, family, display


class GuruSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Populate user fields from Microsoft claims and handle SocialApp edge cases."""

    def get_app(self, request, provider, client_id=None):
        try:
            return super().get_app(request, provider, client_id=client_id)
        except MultipleObjectsReturned:
            qs = SocialApp.objects.filter(provider=provider)
            site_id = getattr(settings, "SITE_ID", None)
            if site_id is not None:
                qs = qs.filter(sites__id=site_id)
            app = qs.order_by("id").first()
            if app:
                return app
            raise
        except SocialApp.DoesNotExist:
            qs = SocialApp.objects.filter(provider=provider)
            app = qs.order_by("id").first()
            if app:
                return app
            raise

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        email = _extract_email(data)
        if email:
            user.email = email
            if not user.username:
                user.username = email.split("@", 1)[0]

        given, family, display = _extract_names(data)
        if given and not user.first_name:
            user.first_name = given
        if family and not user.last_name:
            user.last_name = family
        if display and not (user.first_name or user.last_name):
            user.first_name = display

        return user

    def on_authentication_error(self, request, provider, error=None, exception=None, extra_context=None):
        logger.error(
            "AUTH ERROR - provider=%r error=%r exception=%r",
            getattr(provider, "id", provider),
            error,
            exception,
        )
        return super().on_authentication_error(
            request,
            provider,
            error=error,
            exception=exception,
            extra_context=extra_context,
        )
