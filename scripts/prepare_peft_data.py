#!/usr/bin/env python3
"""
Prepare PEFT/LoRA training data for contract clause LLM.

Loads:
- POC JSON from docs/knowledge/Contract_Positions_POC_GB_Legal_2026-02-19.json
- Accuracy reports from test_results/accuracy_report_*.json (if any)

Outputs data/peft_clause_train.jsonl with chat format:
  {"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}

Generates two task types:
(a) Evidence validation: "Does evidence X describe clause Y? Yes/No"
(b) Semantic edit: "Edit paragraph to align with ideal Z. Output edited text."
"""

import json
import os
from pathlib import Path

# Paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
POC_PATH = PROJECT_ROOT / "docs" / "knowledge" / "Contract_Positions_POC_GB_Legal_2026-02-19.json"
TEST_RESULTS_DIR = PROJECT_ROOT / "test_results"
OUTPUT_PATH = PROJECT_ROOT / "data" / "peft_clause_train.jsonl"

SYSTEM_PROMPT = (
    "You are a legal contract analyst specializing in aerospace supply contracts. "
    "Answer concisely and accurately."
)


def load_poc(path: Path) -> list[dict]:
    """Load POC clauses from JSON."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("clauses", [])


def load_accuracy_reports(dir_path: Path) -> list[dict]:
    """Load all accuracy_report_*.json files."""
    reports = []
    for p in sorted(dir_path.glob("accuracy_report_*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                reports.append(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: could not load {p}: {e}")
    return reports


def extract_evidence_pairs(reports: list[dict]) -> list[tuple[str, str, bool]]:
    """
    Extract (clause, evidence_preview, is_valid) from reports.
    is_valid: True when evidence describes the clause (detected=Yes and has real evidence).
    """
    pairs = []
    seen = set()
    for report in reports:
        for file_data in report.get("files", {}).values():
            if not isinstance(file_data, dict) or "details" not in file_data:
                continue
            for d in file_data["details"]:
                clause = d.get("clause", "")
                evidence = d.get("evidence_preview", "")
                detected = d.get("detected", "")
                # Valid: detected=Yes and evidence is not placeholder
                is_valid = (
                    detected == "Yes"
                    and evidence
                    and "No direct matching clause text found" not in evidence
                )
                key = (clause, evidence[:80])  # dedupe by clause + evidence prefix
                if key not in seen and evidence:
                    seen.add(key)
                    pairs.append((clause, evidence, is_valid))
    return pairs


def build_negative_evidence(clauses: list[dict]) -> list[tuple[str, str, bool]]:
    """Build synthetic negative examples: evidence that does NOT describe the clause."""
    negatives = []
    # Use mismatched evidence: evidence about clause A with question about clause B
    for i, c in enumerate(clauses):
        name = c.get("name", "")
        other_clause = clauses[(i + 1) % len(clauses)]
        # Use ideal_position of another clause as "evidence" - doesn't describe current
        fake_evidence = other_clause.get("ideal_position", "")[:200]
        if name and fake_evidence:
            negatives.append((name, fake_evidence, False))
    return negatives


def build_synthetic_edit_examples(clauses: list[dict]) -> list[tuple[str, str]]:
    """
    Build synthetic edit examples: (user_input, assistant_output).
    Uses ideal_position as target; creates loose/wrong input from keywords.
    """
    # Synthetic "current" paragraphs that need editing toward ideal
    SYNTHETIC_INPUTS = {
        "Limitation of Liability and Exclusion of Consequential Damages": (
            "Liability shall not be limited. Consequential and indirect damages may apply. "
            "The parties waive no remedies."
        ),
        "Applicable / Governing Law - Choice of Law and Jurisdiction": (
            "The law of an unspecified jurisdiction shall apply. "
            "Courts in any country may have jurisdiction."
        ),
        "Dispute Resolution": (
            "Disputes shall be resolved in court. No arbitration or mediation is required."
        ),
        "Firm Price": (
            "Prices may be adjusted at any time. Escalation is unlimited. "
            "The supplier may renegotiate freely."
        ),
        "Force Majeure": (
            "Force majeure includes economic hardship. Payment obligations may be suspended "
            "for any FM event including for delivered goods."
        ),
        "Liquidated Damages": (
            "LD may be framed as a penalty. No cap on delayed value. "
            "LD is not an exclusive remedy."
        ),
        "Orders Extending Beyond Termination": (
            "All orders survive termination indefinitely. No repricing for overhang orders."
        ),
        "Quantity Protection": (
            "Forecast deviations have no consequences. No reimbursement for actuals. "
            "Forecasts never convert to firm POs."
        ),
        "Inventory Requirements": (
            "Unlimited inventory against non-binding forecasts. No cap on RM/FG."
        ),
        "Change Orders Procedure": (
            "Changes may be implemented orally. No signed change order required. "
            "No equitable adjustment for time/price impact."
        ),
    }
    examples = []
    for c in clauses:
        name = c.get("name", "")
        ideal = c.get("ideal_position", "")
        if not name or not ideal:
            continue
        current = SYNTHETIC_INPUTS.get(name)
        if not current:
            # Fallback: use keywords to build a weak version
            kw = c.get("keywords", [])[:4]
            current = f"Clause regarding {', '.join(kw)}. Terms are flexible."
        user = (
            f"Edit the following paragraph to align with the ideal position for "
            f'"{name}". Output only the edited text.\n\n'
            f"Ideal position: {ideal}\n\n"
            f"Current paragraph:\n{current}"
        )
        assistant = ideal
        examples.append((user, assistant))
    return examples


def to_chat_record(system: str, user: str, assistant: str) -> dict:
    """Build a single chat-format training example."""
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
    }


def main() -> None:
    """Write expanded training set (300–500 rows) by default.

    Use ``--legacy`` for the smaller POC + accuracy-report extraction only.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Prepare PEFT clause training JSONL")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Legacy path: POC JSON + test_results only (small file)",
    )
    args = parser.parse_args()
    if args.legacy:
        main_legacy()
        return
    # Prefer the extended generator (plan: 300–500 examples).
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    import build_peft_clause_train_extended as ext  # type: ignore

    ext.main()


def main_legacy() -> None:
    # Ensure data dir exists
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load POC
    if not POC_PATH.exists():
        raise FileNotFoundError(f"POC not found: {POC_PATH}")
    clauses = load_poc(POC_PATH)
    print(f"Loaded {len(clauses)} clauses from POC")

    # Load accuracy reports
    reports = []
    if TEST_RESULTS_DIR.exists():
        reports = load_accuracy_reports(TEST_RESULTS_DIR)
        print(f"Loaded {len(reports)} accuracy reports")
    else:
        print("No test_results directory; using POC-only synthetic data")

    # Evidence validation examples
    evidence_pairs = extract_evidence_pairs(reports)
    evidence_pairs.extend(build_negative_evidence(clauses))

    records = []
    for clause, evidence, is_valid in evidence_pairs:
        user = f"Does the following evidence describe the clause \"{clause}\"?\n\nEvidence:\n{evidence}"
        assistant = "Yes" if is_valid else "No"
        records.append(to_chat_record(SYSTEM_PROMPT, user, assistant))

    # Semantic edit examples (from POC)
    edit_examples = build_synthetic_edit_examples(clauses)
    for user, assistant in edit_examples:
        records.append(to_chat_record(SYSTEM_PROMPT, user, assistant))

    # Pad to at least 20-30 if needed (duplicate edit examples with slight variation)
    target_min = 25
    while len(records) < target_min and edit_examples:
        for user, assistant in edit_examples[: target_min - len(records)]:
            if len(records) >= target_min:
                break
            records.append(to_chat_record(SYSTEM_PROMPT, user, assistant))

    # Write JSONL
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Wrote {len(records)} examples to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
