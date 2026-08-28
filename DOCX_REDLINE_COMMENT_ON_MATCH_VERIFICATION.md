# DOCX Redline – Comments-on-Match Verification Report

## Context

The main agent is implementing:
1. **Comment enrichment** – add `mitigation_recommendation` and `approval_path` to margin comment text
2. **Comments-on-match** – add a margin comment when a paragraph matches, even when the edit fails the validator; only apply redline when the validator passes

---

## 1. Validator Verification

### `_is_valid_edit` with `allow_minimal_replacements` – No Code Path Break

The validator is independent of comments. It is called with `(original_text, edited_text, allow_minimal_replacements=True)` and returns a boolean. No code path breaks when comments are added without redline:

| Scenario | Validator result | Current behavior | With comments-on-match |
|---------|------------------|------------------|-------------------------|
| Pass | `True` | Redline + comment | Same – redline + comment |
| Fail | `False` | `continue` (no output) | Comment only, then `continue` |

**Conclusion:** The validator remains correct. The only change is what happens when it returns `False` – instead of silently skipping, you add a comment. No change to `_is_valid_edit` itself.

---

## 2. `used_paragraph_indexes` and Paragraph Reuse – Critical

### Current Flow

```
match paragraph → validator fails → continue (paragraph NOT added to used_paragraph_indexes)
match paragraph → validator passes → add to used → redline → comment
```

So today, if the validator fails, the paragraph is **not** marked as used. That allows a later instruction with overlapping evidence to match the same paragraph. Because no comment is added, double-comment is not an issue.

### New Flow (Comments-on-Match)

If you add a comment when the validator fails, the same paragraph can later be matched again. That would lead to **double comment** on one paragraph.

### Required Change

**Add `target_idx` to `used_paragraph_indexes` whenever you add a comment**, regardless of whether the validator passed:

- **Validator passes:** add to used → redline → comment ✓
- **Validator fails:** add comment → add to used → continue ✓

So:

```
used_paragraph_indexes.add(target_idx)  # MUST happen for BOTH paths
```

### Recommended Structure

Unified flow – add to `used_paragraph_indexes` as soon as we decide to output a comment (both paths), then branch on validator:

```python
# After: target_para, original_text, edited_text are set

validator_passes = _is_valid_edit(
    original_text, edited_text, allow_minimal_replacements=True
)

# CRITICAL: Mark paragraph as used BEFORE any continue – prevents double-comment/redline
used_paragraph_indexes.add(target_idx)

if validator_passes:
    _clear_paragraph_runs(target_para)
    _write_redline(target_para, original_text, edited_text)

# Comment anchors to runs that exist: new runs (if redline) or original runs (if no redline)
policy_comment = row.get("risk_rationale") or "Deviation requires legal review."
counterfactual_comment = row.get("counterfactual") or "Counterfactual reasoning unavailable."
# ... enrich with mitigation_recommendation, approval_path ...
has_margin_comments = _add_risk_aware_margin_comments(...)

if not validator_passes and render_warnings is not None:
    render_warnings.append(
        f"{row['clause_name']}: validator rejected proposed edit (overlap/length/sentence guardrail)."
    )
```

### Comment Order

Comments must anchor to runs that remain in the paragraph:

| Path | Order | Comment anchor |
|------|-------|----------------|
| Validator passes | 1. Add to used 2. Clear + redline 3. Add comment | New runs from `_write_redline` |
| Validator fails | 1. Add to used 2. Add comment (no clear/redline) | Original runs (unchanged) |

If you add a comment for the validator-fail path, add to `used_paragraph_indexes` first so the paragraph is reserved before any `continue`. The unified structure above achieves this without an explicit `continue`.

---

## 3. Compatibility Issues and Adjustments

### 3.1 Warning Message

When the validator fails, you currently append a warning and `continue`. With comments-on-match, keep that warning so the user still knows the edit was not applied.

### 3.2 Comment Text for Validator-Fail Path

For the comment-only path, consider including in the comment:

- Risk rationale
- Mitigation recommendation (especially useful when no redline is shown)
- Approval path
- Optional: “Suggested edit not applied: [suggested_text/gb_ideal_position] – failed overlap/length guardrail”

That tells the reviewer why there is no redline and what the system would have suggested.

### 3.3 `_add_risk_aware_margin_comments` Signature

To support enrichment, you can:

**Option A:** Add optional `mitigation` and `approval_path` parameters and fold them into the comment text:

```python
def _add_risk_aware_margin_comments(
    doc, target_paragraph, *,
    risk_level: str,
    policy_comment: str,
    counterfactual_comment: str,
    mitigation: str = "",
    approval_path: str = "",
) -> bool:
```

**Option B:** Build enriched text in `build_reviewed_contract_docx` and pass it as `policy_comment` (no change to the function signature).

### 3.4 Green Rows

Green rows are skipped with no comment. That is correct – no deviation, no comment.

---

## 4. Summary Checklist

- [ ] Add `target_idx` to `used_paragraph_indexes` when a comment is added (both validator pass and fail paths).
- [ ] For validator-pass path: redline first, then add comment (unchanged logic).
- [ ] For validator-fail path: add comment to existing runs, then add to used, then continue.
- [ ] Ensure no double-comment and no double-redline by always marking the paragraph as used when it receives any comment.
- [ ] Keep the warning when the validator fails.
- [ ] Enrich comment text with mitigation and approval_path per your design.
