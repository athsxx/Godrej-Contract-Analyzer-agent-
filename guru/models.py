"""Persistence models for analysis jobs and artifacts."""

from __future__ import annotations

import uuid

from django.db import models


class AnalysisJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_id = models.CharField(max_length=128, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    error_message = models.TextField(blank=True)
    config_snapshot = models.JSONField(blank=True, default=dict)
    input_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]


class AnalysisArtifact(models.Model):
    class Kind(models.TextChoices):
        CLAUSE_TABLE = "clause_table", "Clause table"
        PARAGRAPH_MAP = "paragraph_map", "Paragraph map"
        EXECUTIVE_READ = "executive_read", "Executive read"
        SUGGESTIONS = "suggestions", "Suggestions"
        TRACE = "trace", "Trace"

    job = models.ForeignKey(
        AnalysisJob,
        on_delete=models.CASCADE,
        related_name="artifacts",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    version = models.PositiveIntegerField(default=1)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ExecutiveFeedback(models.Model):
    """Legal / executive notes on a session (human-in-the-loop; not online model training)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_id = models.CharField(max_length=128, db_index=True)
    notes = models.TextField(blank=True)
    extra = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
