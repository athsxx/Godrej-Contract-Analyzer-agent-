"""Session rehydration from disk (Celery worker compatibility)."""

from __future__ import annotations

import json

from agents.sample_agent import chat_agent


def test_rehydrate_session_uploads_from_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_agent, "UPLOAD_ROOT", tmp_path)
    sid = "rehydrate-test-sid"
    chat_agent.reset_session(sid)
    session_dir = tmp_path / sid
    session_dir.mkdir(parents=True)
    (session_dir / "contract.txt").write_text("payment terms net 30", encoding="utf-8")
    (session_dir / "_upload_roles.json").write_text(
        json.dumps({"files": [{"name": "contract.txt", "role": "contract"}]}),
        encoding="utf-8",
    )
    assert chat_agent.rehydrate_session_uploads_from_disk(sid) is True
    out = chat_agent.export_session_state(sid)
    names = [f["name"] for f in out.get("files") or []]
    assert "contract.txt" in names


def test_rehydrate_skips_when_memory_already_has_files(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_agent, "UPLOAD_ROOT", tmp_path)
    sid = "rehydrate-skip-sid"
    chat_agent.reset_session(sid)
    # Simulate web process that already has files in memory (rehydrate short-circuits).
    st = chat_agent._ensure_session(sid)
    from pathlib import Path

    from agents.sample_agent.chat_agent import UploadedArtifact

    p = tmp_path / sid / "a.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    st.files.append(
        UploadedArtifact(name="a.txt", path=p, size=1, extras={"full_text": "x", "upload_role": "contract"})
    )
    assert chat_agent.rehydrate_session_uploads_from_disk(sid) is True
