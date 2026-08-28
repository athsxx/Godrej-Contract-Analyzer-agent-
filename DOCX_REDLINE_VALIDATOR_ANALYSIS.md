# DOCX Redline Validator – Analysis and Proposed Changes

## 1. Current Validator Logic

### 1.1 `_token_overlap_score(a, b) -> float`

**Formula:** `|A ∩ B| / max(1, |A|)`  
**Interpretation:** Fraction of tokens in text `a` (typically original) that also appear in text `b` (edited). Asymmetric.

- **Tokens:** `[a-z0-9%]+` extracted from lowercased, normalized text.
- **Role:** Measures how much of the original clause survives in the edit. Low score = edit replaces most wording with new text.
- **Blocks:** Full paragraph replacements with unrelated policy lines (no shared tokens).

---

### 1.2 `_is_valid_edit(original_text, edited_text) -> bool`

| Guardrail | Current threshold | Purpose |
|-----------|-------------------|---------|
| Non-empty | Both stripped non-empty | No blank edits |
| Not identical | `normalize(original) != normalize(edited)` | Prevent no-op |
| Clause body | `_is_clause_body_paragraph(original)` | Original must be sentence-like, length ≥ 45, has `.;:` |
| Min edited tokens | `len(edited_tokens) >= 8` | Block very short fragments |
| Length ratio | `0.55 <= edited/original <= 1.9` | Edited should be 55%-190% of original length |
| Overlap | `overlap >= 0.3` | At least 30% of original tokens must appear in edit |

**Design intent:** Keep edits clause-local and avoid wholesale replacement of long paragraphs with short policy summaries.

---

### 1.3 `_normalize_for_edit(original, row) -> str`

**Order of preference (unchanged):**
1. **Rule-based edits** — clause-specific regex (Limitation of Liability, Force Majeure, Liquidated Damages, Quantity Protection, Inventory Requirements, Change Orders, Orders Extending Beyond Termination). Return immediately when a rule applies.
2. **suggested_text** — only if `_is_valid_edit` passes.
3. **gb_ideal_position** — only if `_is_valid_edit` passes.
4. **mitigation_recommendation** — only if `_is_valid_edit` passes.
5. **original** — no change if nothing passes.

Rule-based edits are already preferred; suggested/ideal/mitigation are fallbacks when no rule applies.

---

## 2. Why Clause Edits Fail

**Typical pattern:** `suggested_text` / `gb_ideal_position` are short policy lines (e.g. “Use approved governing law and jurisdiction combinations (e.g., India/Mumbai).”) while `original` is a long paragraph (e.g. “The courts located in San Francisco, California shall have exclusive jurisdiction…”).

- **Length ratio:** 12 tokens / 50 tokens ≈ 0.24 → fails `< 0.55`.
- **Overlap:** Policy line shares few tokens (e.g. “jurisdiction”, “law”) → 2/50 ≈ 0.04 → fails `< 0.3`.
- **Edited tokens:** 12 ≥ 8 ✓ (often passes).

Result: validator correctly rejects wholesale replacement, but many valid clause edits get blocked.

---

## 3. Proposed Changes

### 3.1 Add `allow_minimal_replacements` parameter

Introduce `_is_valid_edit(original_text, edited_text, *, allow_minimal_replacements=False)`:
- Used when validating `suggested_text` / `gb_ideal_position` / `mitigation_recommendation` in `_normalize_for_edit`.
- Used in `build_reviewed_contract_docx` so edits returned by `_normalize_for_edit` are validated with the same rules.

### 3.2 Relaxed thresholds when `allow_minimal_replacements=True`

| Guardrail | Strict (default) | Relaxed |
|-----------|------------------|---------|
| Length ratio | [0.55, 1.9] | [0.25, 2.5] |
| Min edited tokens | 8 | 5 |
| Overlap | ≥ 0.3 | ≥ 0.15 |

**Rationale:**
- **Length ratio [0.25, 2.5]:** Allows short policy lines (25% of original) while blocking extreme expansion (>2.5×).
- **Min edited tokens 5:** Policy lines with 5–7 tokens (e.g. “Use approved governing law and jurisdiction.”) are acceptable.
- **Overlap ≥ 0.15:** Requires ~15% of original tokens to appear in the edit, blocking completely unrelated text while allowing policy lines that share some key terms.

### 3.3 Safety net

- When `length_ratio < 0.4` and `overlap < 0.2`, always reject — extra guard for very short edits with little shared content.
- Rule-based edits continue to use strict validation; they already produce similar-length, high-overlap output.

### 3.4 Call sites

- `_normalize_for_edit`: `_is_valid_edit(original, suggested, allow_minimal_replacements=True)` (and same for ideal, mitigation).
- `build_reviewed_contract_docx`: `_is_valid_edit(original_text, edited_text, allow_minimal_replacements=True)` — ensures any edit returned by `_normalize_for_edit` is accepted consistently.

---

## 4. What stays unchanged

- Rule-based edits remain first choice in `_normalize_for_edit`.
- Strict validation (or relaxed) is applied uniformly to all edits at the final validation in `build_reviewed_contract_docx`.
- `_normalize_text`, `_is_clause_body_paragraph`, `_is_heading_like`, `_token_overlap_score` logic unchanged.
- Redline flow and margin comments unchanged.

---

## 5. Edge cases

- **Short policy line with almost no overlap:** e.g. 8-token policy, 2 shared tokens with 60-token original → overlap ≈ 0.03 → rejected.
- **Short policy line with moderate overlap:** e.g. 10-token policy, 8 shared tokens with 40-token original → overlap = 0.2 → passes relaxed path.

---

## 6. Future improvements

- Add rule-based edits for more clause types (Applicable Law, Firm Price) to produce minimal in-place substitutions and avoid dependency on suggested/ideal.
- Consider a “policy suggestion as comment only” path when validation fails, so users still see recommendations without redlining.
