"""Reference: end-to-end contract analysis and export workflow.

This module documents stages and entrypoints. Import it for ``WORKFLOW_STAGES``
in tooling or docs; it does not import heavy agent dependencies at load time.
"""

from __future__ import annotations

from typing import List, Tuple

# (stage_id, title, primary_module_or_call)
WORKFLOW_STAGES: List[Tuple[str, str, str]] = [
    ("1", "HTTP: upload / ask / export", "guru.views.workspace_aerospace_contract_analyzer"),
    ("2", "Session + files + optional RAG index on upload", "agents.sample_agent.chat_agent"),
    ("3", "Full-text extraction (DOCX/PDF)", "utils_doc_loader + chat_agent._extract_text"),
    ("4", "Clause analysis (Agent 1)", "agents.sample_agent.agent1_clause_analyzer.run_aerospace_clause_extraction"),
    ("5", "Risk table (Agent 2) + checklist (Agent 3)", "agents.sample_agent.orchestrator.run_analysis_pipeline"),
    ("6", "Chat answers (RAG + LLM)", "agents.sample_agent.chat_agent.answer_question"),
    ("7", "DOCX export: evidence align → match paragraph → edit → validate → write runs", "agents.sample_agent.redline_docx.build_reviewed_contract_docx"),
    ("8", "Optional parallel redline (same logic, threaded)", "agents.sample_agent.redline_docx.build_reviewed_contract_docx_parallel"),
]

__all__ = ["WORKFLOW_STAGES"]
