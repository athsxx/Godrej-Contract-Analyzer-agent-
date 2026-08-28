"""Word comment anchoring: first-through-last run spans full paragraph."""

from __future__ import annotations

import re
import zipfile
from io import BytesIO

import pytest

from agents.sample_agent.redline_docx import Document, _paragraph_comment_anchor_runs


@pytest.mark.skipif(Document is None, reason="python-docx not installed")
def test_anchor_runs_span_first_and_last_when_multiple_runs() -> None:
    doc = Document()
    p = doc.add_paragraph()
    p.add_run("Alpha ")
    p.add_run("Beta")
    runs = _paragraph_comment_anchor_runs(p)
    assert len(runs) == 2
    assert "Alpha" in (runs[0].text or "")
    assert "Beta" in (runs[-1].text or "")


@pytest.mark.skipif(Document is None, reason="python-docx not installed")
def test_saved_docx_comment_range_covers_both_runs() -> None:
    doc = Document()
    p = doc.add_paragraph()
    p.add_run("First ")
    p.add_run("Last")
    doc.add_comment(
        runs=_paragraph_comment_anchor_runs(p),
        text="note",
        author="T",
        initials="T",
    )
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    # Range for first comment id 0: start before First, end after Last
    assert re.search(r'<w:commentRangeStart w:id="0"/>', xml)
    assert re.search(r'<w:commentRangeEnd w:id="0"/>', xml)
    start = xml.index('<w:commentRangeStart w:id="0"/>')
    end = xml.index('<w:commentRangeEnd w:id="0"/>')
    chunk = xml[start:end]
    assert "First" in chunk and "Last" in chunk
