# Semantic Understanding Enhancements

Final development round to improve accuracy, robustness, and precision of the contract analysis agent. The agent now **understands semantics, context, and meaning** instead of relying solely on keywords and regex rules.

## Changes Implemented

### 1. Semantic Edit Generation (`agents/sample_agent/semantic_edit_generator.py`)

**Purpose:** Use the LLM to produce context-aware, meaning-preserving edits that:
- Understand the original text's semantic intent
- Fit naturally in surrounding paragraphs
- Use the same register, tone, and structure as the original
- Make minimal, targeted changes to align with GB ideal position

**When used:** When rule-based edits (regex) produce no change, the semantic generator is invoked as a fallback. This catches clauses that don't match the hard-coded patterns but still need alignment.

### 2. Evidence-to-Clause Validation

**Purpose:** Before using an evidence snippet to find and redline a paragraph, the LLM confirms whether the snippet **actually describes** the claimed clause. Reduces cross-clause pollution where:
- "15 days of receipt" (dispute/escalation clause) was wrongly attributed to Liquidated Damages
- "180 days prior" (design-change clause) was wrongly attributed to Force Majeure
- "loss of business which is incapable of accurate estimation" (compliance) was wrongly attributed to Limitation of Liability

**When used:** Before paragraph matching; if validation fails, the clause is skipped and a warning is added.

### 3. Integration in Redline Flow (`agents/sample_agent/redline_docx.py`)

- **Evidence validation** runs after evidence extraction and before `_find_best_matching_paragraph_index`
- **Semantic edit** runs when `_normalize_for_edit` returns the original (no change)
- Agent 4 verification continues to run on proposed edits before application

### 4. Config Flags (`agents/sample_agent/config.py`)

| Flag | Default | Purpose |
|------|---------|---------|
| `ENABLE_SEMANTIC_EDIT_GENERATION` | `1` | Use LLM to generate context-aware edits when rules fail |
| `ENABLE_EVIDENCE_CLAUSE_VALIDATION` | `1` | Validate evidence belongs to clause before redline matching |

Set via env vars, e.g.:
```bash
export ENABLE_SEMANTIC_EDIT_GENERATION=1
export ENABLE_EVIDENCE_CLAUSE_VALIDATION=1
```

To disable (rules-only, faster but less accurate):
```bash
export ENABLE_SEMANTIC_EDIT_GENERATION=0
export ENABLE_EVIDENCE_CLAUSE_VALIDATION=0
```

## End-to-End Flow (Reviewed DOCX)

```
For each Amber/Red clause:
  1. Extract evidence snippet
  2. [NEW] Validate evidence belongs to clause (LLM) → skip if rejected
  3. Find matching paragraph in document
  4. Get original paragraph text
  5. Apply rule-based edit (_normalize_for_edit)
  6. [NEW] If no change → try semantic edit (LLM)
  7. Validate edit (overlap, length, sentence guardrails)
  8. [Existing] Agent 4 verify (semantic/contextual fit)
  9. Apply redline if all pass
```

## Human-Aiding Design

- **Accuracy:** Semantic understanding reduces wrong-paragraph redlines and cross-clause pollution
- **Precision:** Edits preserve meaning and context; less wholesale replacement with boilerplate
- **Robustness:** Fail-open defaults (validation errors → permit; semantic edit errors → keep original)
- **Transparency:** Agent 4 flags suspicious edits; verification report CSV available for review
