# Knowledge DOCX Parser Mapping Report

**Source DOCX:** `[RFP Tenders-LTAs] Contract Positions for POC_GB Legal_2026.02.19-v1.docx`  
**Target Schema:** `Contract_Positions_POC_GB_Legal_2026-02-19.json` (extended)

---

## 1. Target Clause Structure (Extraction Output)

Each row must map to:

| Field | Source (rows 1–6) | Source (rows 7–10) | Notes |
|-------|-------------------|---------------------|-------|
| `name` | Clause column | Clause column | Full clause title |
| `ideal_position` | Standard Positions (Position 1 primary, or concatenate all) | **GB's Ideal Position** | Do not truncate |
| `approval_path` | Approval for Deviations | Approval for Deviations | Full text including division thresholds |
| `explanation` | Explanation column | Explanation (may include Original Position + Remarks) | Full text |
| `keywords` | Derived from Explanation + Standard Positions | Derived from Explanation + GB's Ideal | Significant terms for evidence matching |

---

## 2. DOCX Table Structure

### 2.1 Columns (expected)

| Index | Column Name | Content |
|-------|-------------|---------|
| 0 | Sr No | 1–10 |
| 1 | Clause | Clause name |
| 2 | Explanation | Detailed guidance, tables, definitions |
| 3 | Standard Positions | Position 1/2/3 (rows 1–6) or GB's Ideal (rows 7–10) |
| 4 | Approval for Deviations | Approval path, possibly division-specific |

**Ambiguity:** Rows 7–10 are described as having "Original Position", "Remarks", "GB's Ideal Position". These may be:
- **Option A:** Sub-sections within the same columns (e.g., Explanation or Standard Positions)
- **Option B:** A different table with different column headers
- **Option C:** Merged cells or multi-row layout per clause

**Parser action:** Detect column headers by text match; if a row has only 3–4 cells due to merged columns, map by semantic content (e.g., text containing "GB's Ideal" → ideal_position).

---

## 3. Row-Type Handling

### 3.1 Rows 1–6 (Standard Positions)

**Standard Positions cell:** Multi-paragraph content with:

- `Position 1` — full clause template (preferred for `ideal_position`)
- `Position 2` — alternate variant
- `Position 3` — alternate variant

**Parsing rules:**

1. Split cell text by line breaks; identify blocks starting with "Position 1", "Position 2", "Position 3".
2. For `ideal_position`: Use **Position 1** as primary; if missing, fall back to first non-empty block.
3. For `standard_positions`: Build `[{ "label": "Position 1", "text": "..." }, ...]` — preserve full text, no truncation.
4. If no "Position N" markers: treat entire cell as single `ideal_position`.

### 3.2 Rows 7–10 (Aerospace Business Critical)

**Standard Positions / content cell:** Contains "Original Position", "Remarks", "GB's Ideal Position" as sections.

**Parsing rules:**

1. Look for section heading "GB's Ideal Position" (case-insensitive); text after it → `ideal_position`.
2. "Original Position" → `original_position` (optional field if schema extended).
3. "Remarks" → append to `explanation` or store separately.
4. If no clear section markers: use entire cell as `ideal_position` and flag for manual review.

---

## 4. Cell Parsing Details

### 4.1 Multi-paragraph cells (Position 1, 2, 3)

**Input pattern:**
```
Position 1
Notwithstanding anything to the contrary... neither party shall be liable for...
a. any losses which are consequential...
b. ...

Position 2
Alternative wording...

Position 3
Another variant...
```

**Extraction:**
- Split on `\n\n` or regex `(?m)^Position\s+(\d+)\s*[\:\-]?\s*`
- Preserve paragraph breaks within each position
- Do NOT truncate

### 4.2 Empty or merged cells

- Empty cell → empty string; do not substitute placeholder.
- Merged cells: python-docx may repeat cell reference; de-duplicate by row index.
- If a row has fewer than 5 cells: map by header order; missing columns → empty string.

---

## 5. Keywords Derivation

Extract from:
- `explanation`
- `ideal_position` / `standard_positions` text

**Strategy:**
- Keep existing manual keywords as base.
- Add: legal terms (e.g. "notwithstanding", "carve-out", "SOW"), percentages (0.5%, 5%, 10%, 20%, 100%), entity names (GnB, SIAC, LCIA, ICC).
- Remove very common words (the, and, of, etc.).
- Max ~15–20 keywords per clause.

---

## 6. Parsing Ambiguities & Edge Cases

| Issue | Description | Suggested handling |
|-------|-------------|---------------------|
| **Header row** | First row may be header; column names may vary (e.g. "Sr No" vs "Sr No.") | Normalize: strip, lower, fuzzy match "sr no", "clause", "explanation", "standard position", "approval" |
| **Multiple tables** | DOCX may have preamble table + main table | Use first table with ≥5 columns and header containing "Clause" |
| **Rows 7–10 layout** | "Original Position", "Remarks", "GB's Ideal" may not be separate columns | Parse Standard Positions cell for section headers; fallback: full cell → ideal_position |
| **Sr No. gaps** | Rows 1–10 expected; blank rows or merged rows | Validate row count; report if ≠ 10 data rows |
| **Encoding** | Special characters, bullets | Preserve UTF-8; normalize bullet chars (•, -, *) if needed |
| **Tables inside cells** | Explanation may have nested tables (e.g. entity table) | python-docx: `cell.tables` for nested tables; concatenate cell text + nested table text |

---

## 7. Validation Checklist

After extraction, verify:

- [ ] Exactly 10 clauses with `id` 1–10
- [ ] Each `name` non-empty
- [ ] Each `ideal_position` non-empty and not truncated (compare length to DOCX cell)
- [ ] Each `approval_path` non-empty
- [ ] `explanation` present for all clauses (currently missing in JSON)
- [ ] Rows 1–6: `standard_positions` has ≥1 position with full text
- [ ] Rows 7–10: `ideal_position` sourced from "GB's Ideal Position" section
- [ ] No placeholder text like "..." or "[truncated]"

---

## 8. Recommended JSON Schema (Extended)

```json
{
  "meta": { "title", "source", "scope", "out_of_scope" },
  "clauses": [
    {
      "id": 1,
      "name": "...",
      "explanation": "...",
      "ideal_position": "...",
      "standard_positions": [
        { "label": "Position 1", "text": "..." },
        { "label": "Position 2", "text": "..." }
      ],
      "approval_path": "...",
      "approval_detail": "...",
      "keywords": ["..."]
    }
  ]
}
```

**Backward compatibility:** Consumers that expect `ideal_position` and `approval_path` only will continue to work. `standard_positions` and `explanation` are additive.

---

## 9. Parser Output Report (Suggested)

When parser runs, emit:

1. **Extraction summary:** Rows parsed, clauses extracted, any rows skipped
2. **Ambiguity log:** Cells that didn't map cleanly, e.g.:
   - "Row 7: No 'GB's Ideal Position' heading found; used full Standard Positions cell"
   - "Row 3: Position 2 block empty"
3. **Length check:** For each clause, report `ideal_position` length vs DOCX source length; flag if truncated
4. **Schema validation:** Pass/fail against checklist in §7

---

## 10. Suggested Parser Fixes (for Loader Implementation)

| Fix | Location | Action |
|-----|----------|--------|
| **Column detection** | Header row | Normalize header text (strip, lower); fuzzy-match "Sr No", "Clause", "Explanation", "Standard Positions", "Approval for Deviations". Support "Sr No." and "GB's Ideal Position" as alternate column labels. |
| **Multi-paragraph Standard Positions** | Rows 1–6 | Split on regex `^Position\s+(\d+)\s*[:\-]?\s*`; preserve paragraph breaks within each position. Use Position 1 as `ideal_position`; store all in `standard_positions` array. Do not truncate. |
| **Rows 7–10 extraction** | Standard Positions cell | Search for "GB's Ideal Position" section (regex or string); extract text after it. If not found, use full cell and log ambiguity. |
| **Explanation mapping** | Explanation column | Map directly to `explanation`; preserve nested tables (python-docx: iterate `cell.tables` and append their cell text). |
| **Approval preservation** | Approval column | Store full text in `approval_path`; add `approval_detail` for division-specific text (e.g. LD 10% vs 5%). |
| **Keywords** | Post-processing | Derive from `explanation` + `ideal_position`; keep legal terms, percentages, entity names; merge with existing manual keywords. |
| **Merged cells** | All cells | python-docx may return duplicate cells for merged regions; de-duplicate by (row_idx, col_idx) or by content. |
| **Nested tables** | Explanation | Flatten `cell.tables` into text before assigning to `explanation`. |
