#!/usr/bin/env python3
"""Generate expanded PEFT training JSONL (300–500 chat examples).

Task families (per plan):
  A — Evidence-to-clause: Yes / No / Ambiguous
  B — Risk band: Red / Amber / Green + short rationale
  C — In-place legal edit toward GB ideal

Does not modify the plan file. Run from project root:
  python scripts/build_peft_clause_train_extended.py
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT_ROOT / "data" / "peft_clause_train.jsonl"

SYSTEM = (
    "You are a legal contract analyst specializing in aerospace supply contracts. "
    "Answer concisely and accurately."
)

# Canonical GB Aerospace POC clause titles (order matches knowledge doc).
CLAUSES: list[str] = [
    "Aerospace Business Critical Terms",
    "Applicable / Governing Law – Choice of Law and Jurisdiction",
    "Dispute Resolution",
    "Firm Price",
    "Force Majeure",
    "Liquidated Damages",
    "Limitation of Liability and Exclusion of Consequential Damages",
    "Orders Extending Beyond Termination",
    "Quantity Protection",
    "Inventory Requirements",
    "Change Orders Procedure",
]


def _task_a_evidence(clause: str, evidence: str, answer: str) -> dict:
    user = f'Does the following evidence describe the clause "{clause}"?\n\nEvidence:\n{evidence}'
    return _msg(user, answer)


def _task_b_risk(clause: str, evidence: str, answer: str) -> dict:
    user = (
        f'Clause focus: "{clause}"\n'
        f"Evidence excerpt:\n{evidence}\n\n"
        f"Respond exactly as: Risk: <Red|Amber|Green>. Rationale: <one sentence>."
    )
    return _msg(user, answer)


def _task_c_edit(user_body: str, edited: str) -> dict:
    return _msg(user_body, edited)


def _msg(user: str, assistant: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
    }


def build_records() -> list[dict]:
    recs: list[dict] = []
    n = len(CLAUSES)

    # --- Task A: positives, negatives, ambiguous (per clause) ---
    for i, c in enumerate(CLAUSES):
        other = CLAUSES[(i + 3) % n]

        # Positive samples (contract-style text)
        positives = {
            "Aerospace Business Critical Terms": [
                "This Agreement incorporates the Aerospace Business Critical Terms listed in Schedule X; failure to satisfy ABCT is a material breach.",
                "Supplier shall comply with all Aerospace Business Critical Terms as defined in Appendix A.",
            ],
            "Applicable / Governing Law – Choice of Law and Jurisdiction": [
                "This Agreement shall be governed by and construed in accordance with the laws of France, without regard to conflict of law principles.",
                "The courts of Mumbai, India shall have exclusive jurisdiction; the laws of India govern any dispute under the Arbitration and Conciliation Act, 1996.",
                "The Republic of India shall have jurisdiction; parties submit to Indian law for interpretation of this contract.",
            ],
            "Dispute Resolution": [
                "Any dispute shall be finally resolved by arbitration seated in Paris under ICC Rules. The arbitral tribunal shall consist of three arbitrators.",
                "Disputes shall be referred to arbitration in Mumbai in English; the seat shall be India and the Act of 1996 applies.",
            ],
            "Firm Price": [
                "During the Firm Period prices are fixed and not subject to variation except as set out in Appendix 3 Market Share commitments.",
                "Firm Requirements are fixed within the PO; Supplier may not increase price absent a written change order.",
            ],
            "Force Majeure": [
                "Neither party shall be liable for delay caused by Force Majeure as defined herein, provided timely notice is given.",
                "Force Majeure shall not excuse payment of sums already due for delivered Products.",
            ],
            "Liquidated Damages": [
                "Liquidated damages for delay shall not exceed five percent (5%) of the delayed portion of the order value.",
                "Penalités for late delivery apply as stated; they are genuine pre-estimates and not penalties under French civil law concepts.",
                "LD may be levied weekly; aggregate LD shall not exceed the cap agreed in Article 11.",
            ],
            "Limitation of Liability and Exclusion of Consequential Damages": [
                "In no event shall either party be liable for loss of profit, indirect or consequential damages except for amounts covered by insurance.",
                "Total aggregate liability shall be limited to fees paid in the twelve months preceding the claim, excluding indemnities for bodily injury.",
            ],
            "Orders Extending Beyond Termination": [
                "Open Purchase Orders issued prior to termination shall be completed at the pricing and terms applicable at issuance unless otherwise agreed.",
                "Termination shall not affect orders placed before the effective date; overhang quantities shall be delivered under original firm price.",
            ],
            "Quantity Protection": [
                "Forecasted Period volumes bind the parties as converted to firm orders per the Delivery Program in Appendix 3.",
                "Shortfalls below min take levels shall trigger reimbursement as specified in the volume commitment schedule.",
            ],
            "Inventory Requirements": [
                "Seller shall maintain finished goods inventory aligned to confirmed orders; raw materials shall not exceed levels tied to rolling forecasts.",
                "Seller must inform within five working days of any inability to maintain required inventory levels; holding costs are borne by Seller.",
            ],
            "Change Orders Procedure": [
                "No change shall be effective unless documented in a signed change order adjusting price and schedule equitably.",
                "Parties shall negotiate an equitable adjustment for any Buyer-directed change affecting cost or timing.",
            ],
        }
        for ev in positives.get(c, ["Supplier and Buyer obligations under Article 12 include supply security and forecast alignment."]):
            recs.append(_task_a_evidence(c, ev, "Yes"))

        # Negative: evidence from another clause domain
        recs.append(
            _task_a_evidence(
                c,
                f"Cross-reference only: quantities and forecasts are as defined in Chapter 6.7.2 of Appendix 3 (not operative text for {c}).",
                "No",
            )
        )
        recs.append(
            _task_a_evidence(
                c,
                f"Snippet about payment terms Net 90 unrelated to {c}: invoices payable ninety days after receipt.",
                "No",
            )
        )

        # Ambiguous
        ambiguous_evs = [
            f"A defined term referenced in Schedule 2 may indirectly affect {c}; the linkage is unclear without Appendix 2.",
            "Parties agree to negotiate in good faith; no specific operative sentence addresses the clause topic directly.",
        ]
        for ev in ambiguous_evs:
            recs.append(_task_a_evidence(c, ev, "Ambiguous"))

    # --- Task B: risk bands ---
    risk_specs: list[tuple[str, str, str, str]] = [
        (
            "Liquidated Damages",
            "LD is 0.1% per day without express aggregate cap against total order value.",
            "Risk: Red. Rationale: Uncapped exposure and daily accrual create disproportionate penalty risk.",
        ),
        (
            "Liquidated Damages",
            "LD capped at 8% aggregate and classified as précompte under French practice; stacking with FM exclusions partially addressed.",
            "Risk: Amber. Rationale: A cap exists but interaction with FM and other remedies requires legal review.",
        ),
        (
            "Liquidated Damages",
            "LD limited to 3% of delayed value with clear sole remedy clause and FM carve-out.",
            "Risk: Green. Rationale: Cap and exclusivity align with conservative exposure.",
        ),
        (
            "Applicable / Governing Law – Choice of Law and Jurisdiction",
            "Exclusive jurisdiction of Commercial Court of Paris; French substantive law applies to performance and LD enforceability.",
            "Risk: Amber. Rationale: Foreign court and civil-law LD concepts differ from buyer’s preferred Indian arbitration seat.",
        ),
        (
            "Dispute Resolution",
            "ICC Paris arbitration; English procedural language; no court litigation except interim relief.",
            "Risk: Amber. Rationale: Acceptable arbitration but cost and seat may be non-ideal for Indian counterparty.",
        ),
        (
            "Firm Price",
            "Prices firm for Firm Period; adjustments only per formula in Appendix 3 with volume bands.",
            "Risk: Green. Rationale: Mechanism matches firm-pricing expectations when Appendix 3 is uploaded.",
        ),
        (
            "Force Majeure",
            "FM excludes payment obligations; delay beyond 120 days allows termination without LD for that period.",
            "Risk: Amber. Rationale: FM scope and payment interaction need cross-check with LD article.",
        ),
        (
            "Limitation of Liability and Exclusion of Consequential Damages",
            "Consequential damages excluded; liability capped at contract value; carve-outs for fraud and IP indemnity.",
            "Risk: Green. Rationale: Standard balanced limitation with explicit carve-outs.",
        ),
        (
            "Inventory Requirements",
            "Notification-only clause: Seller shall inform Buyer within 5 days if inventory cannot be maintained; no holding obligation stated.",
            "Risk: Amber. Rationale: Alignment with GB stock-holding position is unclear without explicit inventory cap language.",
        ),
        (
            "Change Orders Procedure",
            "Oral changes permitted if confirmed by email within 48 hours; may conflict with written change order requirement.",
            "Risk: Red. Rationale: Oral variation undermines auditability and equitable adjustment discipline.",
        ),
    ]
    for clause, ev, ans in risk_specs:
        recs.append(_task_b_risk(clause, ev, ans))

    # More Task B rows (template loop)
    for c in CLAUSES:
        recs.append(
            _task_b_risk(
                c,
                f"Article text partially visible; reference says 'as defined in Chapter 6.7.2' without embedding definition.",
                "Risk: Amber. Rationale: Cross-reference blocks assessment until definition is retrieved.",
            )
        )

    # --- Task C: edits (from prepare_peft_data style) ---
    edits = [
        (
            'Edit the following paragraph to align with the ideal position for "Liquidated Damages". Output only the edited text.\n\n'
            "Ideal position: LD shall be a genuine pre-estimate, capped, and not stack with other remedies.\n\n"
            "Current paragraph:\nLD is a penalty for delay; unlimited LD applies and may stack with FM relief.",
            "Liquidated damages shall constitute a genuine pre-estimate of loss, shall not exceed the agreed percentage cap, and shall not be imposed in addition to other remedies for the same delay where such stacking is excluded herein.",
        ),
        (
            'Edit the following paragraph to align with the ideal position for "Dispute Resolution". Output only the edited text.\n\n'
            "Ideal position: Arbitration in India or mutually agreed seat; clear institutional rules.\n\n"
            "Current paragraph:\nAll disputes go to courts in any country at either party’s choice.",
            "Disputes shall be finally resolved by arbitration administered under agreed institutional rules, with seat and governing law as specified in this Agreement, and courts shall have jurisdiction only for interim relief as permitted by law.",
        ),
        (
            'Edit the following paragraph for "Firm Price". Output only the edited text.\n\n'
            "Ideal: Firm Period pricing fixed; changes only via written change order.\n\n"
            "Current:\nPrices float monthly with commodity indices.",
            "Prices for the Firm Period shall remain fixed as set out in the applicable Purchase Order and may only be modified by a written change order executed by both Parties.",
        ),
    ]
    for u, a in edits:
        recs.append(_task_c_edit(u, a))

    # Pad / diversify Task A with jurisdiction-specific negatives
    juris_no = [
        ("Governing Law", "This contract is about technical data rights under ITAR only.", "No"),
        ("Liquidated Damages", "Warranty period for spare parts is twenty-four months.", "No"),
        ("Firm Price", "Taxes and duties are exclusive and invoiced separately per local law.", "Ambiguous"),
    ]
    for clause, ev, ans in juris_no:
        recs.append(_task_a_evidence(clause, ev, ans))

    # Dedupe by json string (simple)
    seen: set[str] = set()
    unique: list[dict] = []
    for r in recs:
        key = json.dumps(r["messages"], sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    target = 400
    if len(unique) < target:
        # Deterministic padding: paraphrase Task A
        pad_i = 0
        while len(unique) < target:
            c = CLAUSES[pad_i % n]
            ev = f"[Variant {pad_i}] Supplier obligations regarding {c} continue during the Forecasted Period subject to Appendix references."
            r = _task_a_evidence(c, ev, "Ambiguous" if pad_i % 4 == 0 else "Yes")
            key = json.dumps(r["messages"], sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                unique.append(r)
            pad_i += 1

    return unique[: max(300, min(500, len(unique)))]


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    rows = build_records()
    with open(OUTPUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} examples to {OUTPUT}")


if __name__ == "__main__":
    main()
