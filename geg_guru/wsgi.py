"""WSGI config for the standalone custom-dev project."""

from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geg_guru.settings")

application = get_wsgi_application()
