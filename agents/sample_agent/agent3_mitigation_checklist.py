# agent3_mitigation_checklist.py
# Purpose: Produce a compact " Risk Mitigation Checklist" from Agent 2's RAG table.
# No LLM calls here — it's purely a deterministic transform so it's fast and stable.

import re
from typing import List, Dict


HEADER = "🔍 **Risk Mitigation Checklist**"
SOURCE_HEADER_PATTERN = r"\|\s*Clause\s*\|\s*Risk\s*\|\s*RAG\s*\|\s*Rationale\s*\|\s*Mitigation\s*\|\s*Evidence/Location\s*\|"


def _parse_agent2_table(agent2_markdown: str) -> List[Dict[str, str]]:
    """
    Parse Agent 2's RAG table:
      | Clause | Risk | RAG | Rationale | Mitigation | Evidence/Location |

    Returns a list of rows (dicts). Robust to minor spacing.
    """
    lines = (agent2_markdown or "").splitlines()

    # Find the header line of the Agent 2 table
    header_idx = None
    for i, ln in enumerate(lines):
        if re.search(SOURCE_HEADER_PATTERN, ln, re.IGNORECASE):
            header_idx = i
            break
    if header_idx is None:
        return []

    # Data starts two lines after header (header + separator)
    data_rows = []
    for ln in lines[header_idx + 2 :]:
        if not ln.strip().startswith("|"):
            break  # stop at first non-table line
        # Skip separator rows if any appear mid-table
        if re.match(r"\|\s*-+\s*\|\s*-+\s*\|\s*-+\s*\|\s*-+\s*\|\s*-+\s*\|\s*-+\s*\|", ln):
            continue

        parts = [p.strip() for p in ln.strip().strip("|").split("|")]
        if len(parts) < 6:
            # attempt a gentle fix if the line has trailing pipes missing
            while len(parts) < 6:
                parts.append("")
        clause, risk, rag, rationale, mitigation, evidence = parts[:6]
        data_rows.append(
            {
                "clause": clause,
                "risk": risk,
                "rag": rag,
                "rationale": rationale,
                "mitigation": mitigation,
                "evidence": evidence,
            }
        )
    return data_rows


def _is_risky_row(row: Dict[str, str]) -> bool:
    """
    Keep only genuinely risky items.
    - Drop the synthetic "No risks identified" row.
    - Prefer rows with RAG 🟥 or 🟧. (If missing, keep it as risky just in case.)
    """
    clause = (row.get("clause") or "").strip().lower()
    if clause.startswith("no risks identified"):
        return False

    rag = (row.get("rag") or "").strip()
    if rag in ("🟥", "🟧"):
        return True
    # If RAG is absent but it's in the risks table, keep it.
    return True


def _mk_checklist_table(rows: List[Dict[str, str]]) -> str:
    """
    Build the compact 3-column checklist table:
      | Clause | Risk | Mitigation Recommendation |
    """
    out = []
    out.append(HEADER)
    out.append("")
    out.append("| Clause | Risk | Mitigation Recommendation |")
    out.append("|--------|------|---------------------------|")

    if not rows:
        out.append("| No risks identified | - | - |")
        return "\n".join(out)

    for r in rows:
        clause = r.get("clause", "").strip()
        risk = r.get("risk", "").strip()
        mitigation = r.get("mitigation", "").strip() or "-"
        # Keep the text compact (Streamlit will handle wrapping)
        out.append(f"| {clause} | {risk} | {mitigation} |")

    return "\n".join(out)


def generate_mitigation_checklist(agent2_output_markdown: str) -> str:
    """
    Public entry point.
    Input: Agent 2 markdown (RAG table).
    Output: '🔍 Risk Mitigation Checklist' markdown with 3 columns.
    """
    rows = _parse_agent2_table(agent2_output_markdown)
    risky = [r for r in rows if _is_risky_row(r)]
    return _mk_checklist_table(risky)


def generate_mitigation_checklist_from_table(clause_table: List[Dict[str, str]]) -> str:
    """Build checklist directly from the structured Agent 1 clause table."""
    rows: List[Dict[str, str]] = []
    for idx, row in enumerate(clause_table or [], start=1):
        risk_level = (row.get("risk_level") or "Amber").strip()
        detected = (row.get("detected") or "Unclear").strip()
        if risk_level == "Green" and detected == "Yes":
            continue
        rows.append(
            {
                "clause": f"{idx}. {(row.get('clause_name') or '').strip()}",
                "risk": (row.get("risk_trigger") or row.get("risk_rationale") or "Requires legal review.").strip(),
                "mitigation": (
                    row.get("mitigation_recommendation")
                    or "Route to Legal for clause-specific mitigation."
                ).strip(),
                "rag": "🟥" if risk_level == "Red" else "🟧",
            }
        )
    return _mk_checklist_table(rows)


# --- Optional quick test ---
if __name__ == "__main__":
    sample = """
## Risk Analysis and Details

| Clause | Risk | RAG | Rationale | Mitigation | Evidence/Location |
|--------|------|-----|-----------|------------|-------------------|
| 1. Payment Terms | Advance payment only 10% (vs. 45% required). Net 60 days (vs. 30 days). | 🟥 | Cash flow strain | Negotiate higher upfront (30–45%) and Net 30; milestone-based invoicing [1]. | [1] |
| 3. Liquidated Damages (LD) | Documentation LD applies; equipment LD 0.1%/day (≈0.7%/week), max 8%; aggregate LD 10%. | 🟥 | High penalty exposure | Seek doc LD exemption; 0.5%/week; cap 5% [1]. | [1] |
| 14. Consequential Damages | Excluded for both parties. | 🟩 | Acceptable | - | [2] |
"""
    print(generate_mitigation_checklist(sample))
