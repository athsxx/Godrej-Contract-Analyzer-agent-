"""Celery application instance for geg_guru."""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geg_guru.settings")

app = Celery("geg_guru")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
