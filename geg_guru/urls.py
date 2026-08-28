"""Root URL config for the standalone custom-dev scaffold."""

from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

from guru import views as guru_views
from guru import views_analysis

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("login/", guru_views.login, name="login"),
    path("", guru_views.home, name="home"),
    path("aerospace/contract-analyzer/", guru_views.workspace_aerospace_contract_analyzer, name="workspace_aerospace_contract_analyzer"),
    path(
        "aerospace/contract-analyzer/download-reviewed-docx/",
        guru_views.download_reviewed_contract_docx,
        name="download_reviewed_contract_docx",
    ),
    path(
        "aerospace/contract-analyzer/download-clause-csv/",
        guru_views.download_clause_csv,
        name="download_clause_csv",
    ),
    path(
        "aerospace/contract-analyzer/download-contract-commentary-docx/",
        guru_views.download_contract_commentary_docx,
        name="download_contract_commentary_docx",
    ),
    path("api/analysis/jobs/", views_analysis.analysis_job_create, name="analysis_job_create"),
    path("api/analysis/jobs/<uuid:job_id>/", views_analysis.analysis_job_detail, name="analysis_job_detail"),
]
