#!/usr/bin/env python3
"""
Test upload and analysis using a document from the data folder.
Simulates the full flow: upload -> ask -> (optional) generate reviewed DOCX.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# Smoke test: export all suggested redlines without saving checkbox selection (override with REQUIRE_REDLINE_HITL_ACCEPTANCE=1 to test HITL).
os.environ.setdefault("REQUIRE_REDLINE_HITL_ACCEPTANCE", "0")

# Use Django setup
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geg_guru.settings")
django.setup()

from django.test import Client
from django.contrib.sessions.models import Session


def main():
    data_dir = PROJECT_ROOT / "data"
    doc_path = data_dir / "sample_supply_contract.docx"
    if not doc_path.exists():
        print(f"ERROR: No document at {doc_path}")
        print("Create one with: python -c \"from docx import Document; d=Document(); d.add_paragraph('Test'); d.save('data/sample.docx')\"")
        sys.exit(1)

    client = Client()
    # Get a session
    client.get("/aerospace/contract-analyzer/")
    session_key = client.session.session_key
    if not session_key:
        client.get("/aerospace/contract-analyzer/")
        session_key = client.session.session_key
    print(f"Session: {session_key}")

    # Upload (Django test client: "files" is the form field name for getlist("files"))
    with open(doc_path, "rb") as f:
        resp = client.post(
            "/aerospace/contract-analyzer/",
            {"action": "upload", "files": f},
            format="multipart",
        )
    if resp.status_code != 200:
        print(f"Upload failed: {resp.status_code}")
        print(resp.content[:500] if hasattr(resp, "content") else "")
        sys.exit(1)
    print("Upload OK")

    # Ask (trigger analysis)
    resp = client.post(
        "/aerospace/contract-analyzer/",
        {"action": "ask", "message": "Analyze the contract and identify clause risks."},
    )
    if resp.status_code != 200:
        print(f"Ask failed: {resp.status_code}")
        if hasattr(resp, "content"):
            print(resp.content[:800].decode(errors="replace"))
        sys.exit(1)

    ctx = resp.context if hasattr(resp, "context") else {}
    reply = (ctx.get("assistant_reply") or "") if ctx else ""
    counterfactuals = (ctx.get("assistant_counterfactuals") or "") if ctx else ""
    warnings = (ctx.get("warnings") or []) if ctx else []

    # Fallback: parse HTML for chat content if context unavailable
    if not reply and hasattr(resp, "content"):
        html = resp.content.decode(errors="replace")
        if "Clause analysis completed" in html:
            reply = "Clause analysis completed (extracted from HTML)"
        if "counterfactual" in html.lower():
            counterfactuals = "(counterfactuals present in response)"

    print("\n--- Assistant Reply ---")
    print(reply[:500] + "..." if len(reply) > 500 else reply or "(no reply)")
    print("\n--- Counterfactuals ---")
    print(counterfactuals[:400] + "..." if len(counterfactuals) > 400 else counterfactuals or "(none)")
    if warnings:
        print("\n--- Warnings ---")
        for w in warnings:
            print(f"  - {w}")

    # Generate reviewed DOCX only when redline export is enabled (default off in config).
    from agents.sample_agent import chat_agent
    from agents.sample_agent import config as agent_config

    if getattr(agent_config, "ENABLE_REDLINE_DOCX_EXPORT", False):
        try:
            result = chat_agent.generate_reviewed_contract_docx(session_key)
            print(f"\n--- Reviewed DOCX ---")
            print(f"Path: {result.get('path')}")
            print(f"Warnings: {result.get('warnings', [])}")
            print(f"Verification flags: {len(result.get('verification_report', []))}")
        except Exception as e:
            print(f"\nReviewed DOCX: {e}")
    else:
        print("\n--- Reviewed DOCX --- (skipped: ENABLE_REDLINE_DOCX_EXPORT=0)")

    print("\nDone.")


if __name__ == "__main__":
    main()
