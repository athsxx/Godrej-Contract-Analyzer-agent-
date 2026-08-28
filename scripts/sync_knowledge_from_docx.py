#!/usr/bin/env python3
"""
Parse [RFP Tenders-LTAs] Contract Positions DOCX and output JSON.

Table columns: Sr No, Clause, Explanation, Standard Positions, Approval for Deviations.
- Rows 1-6: Standard Positions has Position 1/2/3 (multi-paragraph, line-break separated)
- Rows 7-10 (Aerospace Business Critical): Standard Positions has Original Position, Remarks, GB's Ideal Position

Output schema: { meta, clauses } with id, name, ideal_position, approval_path, explanation, keywords.
See docs/knowledge/KNOWLEDGE_PARSER_MAPPING_REPORT.md for mapping details.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    from docx import Document as DocxDocument
except ImportError:
    print("Requires python-docx: pip install python-docx")
    sys.exit(1)


# Column header normalization (lowercase, minimal)
COL_ALIASES = {
    "sr no": ["sr no", "sr no.", "s.no", "s no", "serial"],
    "clause": ["clause", "clause name"],
    "explanation": ["explanation", "remarks"],
    "standard positions": ["standard positions", "standard position", "gb's ideal position", "gb ideal position"],
    "approval": ["approval for deviations", "approval", "deviation"],
}


def _normalize_header(cell_text: str) -> str:
    return (cell_text or "").strip().lower()


def _matches_column(cell_text: str, col_name: str) -> bool:
    n = _normalize_header(cell_text)
    aliases = COL_ALIASES.get(col_name, [col_name])
    return any(a in n for a in aliases)


def _find_header_indices(header_cells: list[str]) -> dict[str, int]:
    """Map column names to 0-based indices."""
    out: dict[str, int] = {}
    for idx, cell in enumerate(header_cells):
        t = (cell or "").strip()
        if not t:
            continue
        n = _normalize_header(t)
        if "sr" in n and ("no" in n or "s.no" in n):
            out["sr_no"] = idx
        elif "clause" in n:
            out["clause"] = idx
        elif "explanation" in n or "remark" in n:
            out["explanation"] = idx
        elif "standard" in n or "position" in n or "ideal" in n:
            out["standard_positions"] = idx
        elif "approval" in n or "deviation" in n:
            out["approval"] = idx
    return out


def _split_positions(text: str) -> list[tuple[str, str]]:
    """Split Standard Positions cell by Position 1/2/3. Returns [(label, text), ...]."""
    if not (text or "").strip():
        return []
    # Match "Position 1" or "Position 1:" or "Position 2 -" etc.
    pattern = re.compile(r"(?mi)^Position\s+(\d+)\s*[:\-]?\s*", re.MULTILINE)
    parts: list[tuple[str, str]] = []
    last_end = 0
    for m in pattern.finditer(text):
        if m.start() > last_end:
            chunk = text[last_end : m.start()].strip()
            if chunk and parts:
                # Append to previous position
                prev_label, prev_text = parts[-1]
                parts[-1] = (prev_label, prev_text + "\n\n" + chunk)
            elif chunk and not parts:
                parts.append(("Position 0 (preamble)", chunk))
        label = f"Position {m.group(1)}"
        rest_start = m.end()
        next_m = pattern.search(text, rest_start)
        chunk = text[rest_start : next_m.start() if next_m else None].strip()
        parts.append((label, chunk))
        last_end = next_m.start() if next_m else len(text)
    if not parts and text.strip():
        parts.append(("Full text", text.strip()))
    return parts


def _extract_gb_ideal_from_cell(text: str) -> tuple[str, str]:
    """For rows 7-10: extract GB's Ideal Position section. Returns (ideal_text, remainder)."""
    if not (text or "").strip():
        return ("", "")
    # Look for "GB's Ideal Position" or "GB Ideal Position" section
    pattern = re.compile(
        r"(?mi)^(?:GB'?s?\s+)?Ideal\s+Position\s*[:\-]?\s*(.*?)(?=^(?:Original|Remarks|$)|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(text)
    if m:
        ideal = m.group(1).strip()
        return (ideal, text[: m.start()] + text[m.end() :])
    # Fallback: use full text
    return (text.strip(), "")


def _derive_keywords(explanation: str, ideal: str, existing: list[str]) -> list[str]:
    """Derive keywords from explanation + ideal text. Keep existing if provided."""
    combined = f"{explanation or ''} {ideal or ''}".lower()
    # Significant terms (legal, numbers, entities)
    candidates = set(existing) if existing else set()
    # Numbers and percentages
    for m in re.finditer(r"\d+\.?\d*%?", combined):
        candidates.add(m.group(0))
    # Words 3+ chars, exclude common
    stop = {"the", "and", "for", "with", "not", "any", "all", "may", "shall", "this", "that"}
    for w in re.findall(r"\b[a-z]{3,}\b", combined):
        if w not in stop:
            candidates.add(w)
    # Prioritize: existing, then legal terms
    legal_terms = {
        "liability", "cap", "consequential", "indirect", "damages", "notwithstanding",
        "governing", "law", "jurisdiction", "arbitration", "mediation", "siac", "lcia", "icc",
        "firm", "price", "escalation", "force", "majeure", "liquidated", "termination",
        "forecast", "deviation", "inventory", "change", "order", "equitable", "sow",
    }
    result = list(existing)
    for t in legal_terms:
        if t in combined and t not in result:
            result.append(t)
    for c in sorted(candidates):
        if c not in result and len(result) < 20:
            result.append(c)
    return result[:20]


def _cell_text(cell) -> str:
    """Extract full text from cell, including nested tables."""
    parts = [(cell.text or "").strip()]
    for nested in getattr(cell, "tables", []) or []:
        for row in nested.rows:
            for c in row.cells:
                parts.append((c.text or "").strip())
    return "\n".join(p for p in parts if p)


def parse_contract_positions_docx(docx_path: str | Path) -> tuple[dict, list[dict]]:
    """
    Parse DOCX and return (payload, ambiguities).

    payload: { meta, clauses }
    ambiguities: list of { "row", "issue", "detail" }
    """
    path = Path(docx_path)
    if not path.exists():
        raise FileNotFoundError(f"DOCX not found: {path}")

    doc = DocxDocument(str(path))
    ambiguities: list[dict] = []

    # Find main table (first with 5 columns)
    target_table = None
    for table in doc.tables:
        if table.rows and len(table.rows[0].cells) >= 4:
            target_table = table
            break

    if not target_table:
        return ({"meta": {"error": "No suitable table found"}, "clauses": []}, ambiguities)

    rows = list(target_table.rows)
    if len(rows) < 2:
        return ({"meta": {"error": "Table has no data rows"}, "clauses": []}, ambiguities)

    # Header row
    header_cells = [_cell_text(c) for c in rows[0].cells]
    col_map = _find_header_indices(header_cells)

    if "clause" not in col_map:
        ambiguities.append({"row": 0, "issue": "Header mapping", "detail": f"Could not find Clause column. Headers: {header_cells}"})

    data_start = 1
    clauses: list[dict] = []

    for ri, row in enumerate(rows[data_start:], start=data_start):
        cells = [_cell_text(c) for c in row.cells]
        if len(cells) < 2:
            continue

        sr_no = cells[col_map.get("sr_no", 0)] if col_map.get("sr_no") is not None else ""
        clause_name = cells[col_map.get("clause", 1)] if col_map.get("clause") is not None else ""
        explanation = cells[col_map.get("explanation", 2)] if col_map.get("explanation") is not None else ""
        standard_pos = cells[col_map.get("standard_positions", 3)] if col_map.get("standard_positions") is not None else ""
        approval = cells[col_map.get("approval", 4)] if col_map.get("approval") is not None else ""

        if not clause_name and not standard_pos:
            continue

        clause_id = ri  # 1-based
        try:
            sn = int(sr_no) if sr_no and sr_no.isdigit() else ri
            clause_id = sn
        except ValueError:
            pass

        is_aerospace_critical = clause_id >= 7

        if is_aerospace_critical:
            ideal_text, _ = _extract_gb_ideal_from_cell(standard_pos)
            if not ideal_text:
                ideal_text = standard_pos
                ambiguities.append({"row": ri, "issue": "No GB's Ideal section", "detail": "Used full Standard Positions cell for ideal_position"})
            standard_positions = [{"label": "GB's Ideal Position", "text": ideal_text}] if ideal_text else []
        else:
            positions = _split_positions(standard_pos)
            if len(positions) > 1:
                ideal_text = next((p[1] for p in positions if p[0] == "Position 1"), positions[0][1] if positions else "")
                standard_positions = [{"label": lbl, "text": txt} for lbl, txt in positions if txt]
            else:
                ideal_text = standard_pos
                standard_positions = [{"label": "Full text", "text": standard_pos}] if standard_pos else []

        keywords = _derive_keywords(explanation, ideal_text or standard_pos, [])

        clauses.append({
            "id": clause_id,
            "name": clause_name or f"Clause {clause_id}",
            "explanation": explanation,
            "ideal_position": ideal_text or standard_pos or "",
            "standard_positions": standard_positions,
            "approval_path": approval or "",
            "keywords": keywords,
        })

    meta = {
        "title": "GB Aerospace Critical Positions for POC",
        "source": path.name,
        "scope": "Supply contracts where Aerospace is supplying goods",
        "out_of_scope": [
            "purchase/procurement contracts",
            "sub-contracting",
            "strategic alliances",
            "consortium agreements",
            "NDA/confidentiality agreements",
        ],
    }

    # Validation
    if len(clauses) != 10:
        ambiguities.append({"row": "summary", "issue": "Row count", "detail": f"Expected 10 clauses, got {len(clauses)}"})

    for c in clauses:
        if not c.get("ideal_position"):
            ambiguities.append({"row": c.get("id"), "issue": "Empty ideal_position", "detail": c.get("name", "")})
        if len(c.get("ideal_position", "")) < 20 and c.get("standard_positions"):
            ambiguities.append({"row": c.get("id"), "issue": "Possible truncation", "detail": f"ideal_position very short ({len(c.get('ideal_position',''))} chars)"})

    payload = {"meta": meta, "clauses": clauses}
    return (payload, ambiguities)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Parse Contract Positions DOCX to JSON")
    ap.add_argument("docx", nargs="?", help="Path to DOCX file")
    ap.add_argument("-o", "--output", help="Output JSON path")
    ap.add_argument("--report-ambiguities", action="store_true", help="Print ambiguity report to stderr")
    args = ap.parse_args()

    docx_path = args.docx or Path(__file__).resolve().parents[1] / "docs" / "knowledge" / "[RFP Tenders-LTAs] Contract Positions for POC_GB Legal_2026.02.19-v1.docx"
    if not Path(docx_path).exists():
        print(f"DOCX not found: {docx_path}", file=sys.stderr)
        print("Usage: python sync_knowledge_from_docx.py <path_to_docx> [-o output.json]")
        sys.exit(1)

    payload, ambiguities = parse_contract_positions_docx(docx_path)

    if args.report_ambiguities and ambiguities:
        print("Ambiguities:", file=sys.stderr)
        for a in ambiguities:
            print(f"  Row {a['row']}: {a['issue']} - {a['detail']}", file=sys.stderr)

    out_path = args.output or Path(__file__).resolve().parents[1] / "docs" / "knowledge" / "Contract_Positions_POC_GB_Legal_2026-02-19.json"

    # Backward-compat: ensure ideal_position is set even if we use standard_positions
    for c in payload.get("clauses", []):
        if not c.get("ideal_position") and c.get("standard_positions"):
            c["ideal_position"] = c["standard_positions"][0].get("text", "")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(payload.get('clauses', []))} clauses to {out_path}")
    if ambiguities:
        print(f"Ambiguities: {len(ambiguities)} (use --report-ambiguities for details)")


if __name__ == "__main__":
    main()
