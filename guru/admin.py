"""Django admin registration for guru models."""

from django.contrib import admin

from .models import AnalysisArtifact, AnalysisJob, ExecutiveFeedback


@admin.register(AnalysisJob)
class AnalysisJobAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "session_id", "created_at", "updated_at")


@admin.register(ExecutiveFeedback)
class ExecutiveFeedbackAdmin(admin.ModelAdmin):
    list_display = ("id", "session_id", "created_at")
    search_fields = ("session_id", "notes")


@admin.register(AnalysisArtifact)
class AnalysisArtifactAdmin(admin.ModelAdmin):
    list_display = ("id", "job", "kind", "version", "created_at")
