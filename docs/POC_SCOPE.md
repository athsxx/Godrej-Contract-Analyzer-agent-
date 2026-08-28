# POC Scope – Aerospace Contract Analyzer (Supply Contracts)

## Context

- **Legal positions in supply contracts**: Besides transaction-specific risks, GB Legal evaluates **~52 positions** in contracts where Aerospace supplies goods (legal, financial, operational, business-critical).
- **Risk profile**: Different for **procurement/purchase** vs **other document types** (consortiums, strategic alliances, teaming agreements, sub-contracting, etc.). Those (~200–250 positions) are out of scope for this POC.
- **POC limitation**: To reduce bias/hallucination/errors, the POC evaluates **10 critical positions** in **supply contracts** only: flag risks and propose mitigation. All other positions and agreement types are for a later stage.

## Scope Limitation (from source document)

- Only **10 positions** are in scope for the POC.
- Positions are **non-exhaustive**; full playbooks (Contracts Playbook, Aerospace Playbook) cover 52+ supply positions.
- This document applies **only where Aerospace is supplying goods**. It must **not** be used for purchase/procurement, sub-contracting, strategic alliances, consortiums, etc.
- **Legal disclaimer**: Outputs are for POC validation only. Positions must be routed through Legal and must not be put into commercial practice without legal approvals.

---

## 10 Clauses (POC)

| # | Clause | Approval for deviations |
|---|--------|-------------------------|
| 1 | **Limitation of Liability and Exclusion of Consequential Damages** | Exceeds 100% of contract value → ERMC approval |
| 2 | **Applicable / Governing Law – Choice of Law and Jurisdiction** | Any other governing law than stated → BU Head |
| 3 | **Dispute Resolution** | Legal Team to decide |
| 4 | **Firm Price** | ERMC if Term > 2 years or Value > 25cr |
| 5 | **Force Majeure** | Legal team in consultation with Business Team |
| 6 | **Liquidated Damages** | Division-dependent: Aerospace/Appliances/etc. → ERMC when LD > 10%; Construction/E&E/etc. → when LD > 5% |
| 7 | **Orders Extending Beyond Termination** | Legal team in consultation with Business Team |
| 8 | **Quantity Protection** | Legal team in consultation with Business Team |
| 9 | **Inventory Requirements** | Legal team in consultation with Business Team |
| 10 | **Change Orders Procedure** | Legal team in consultation with Business Team |

---

## Document structure (per clause)

For each of the 10 clauses, the source document provides:

1. **Explanation** – What the clause is and what GB expects (e.g. liability cap, exclusions, definitions).
2. **Standard positions (GB’s ideal)** – Preferred wording/positions (Position 1, 2, 3 etc. where applicable).
3. **Approval for deviations** – Who must approve if the contract deviates (ERMC, BU Head, Legal, Legal+Business).

---

## Knowledge asset

- **Structured knowledge**: `docs/knowledge/Contract_Positions_POC_GB_Legal_2026-02-19.json` (derived from the DOCX for clause-wise processing).
- Use this as the **canonical knowledge base** for the POC agent: RAG ingestion, retrieval, and answers should be grounded in this document (and optionally user-uploaded contracts) to avoid hallucination.

---

## Agent design implications

1. **Grounding**: Agent answers on the 10 clauses must cite this document; no policy beyond these 10 for supply contracts in POC.
2. **Approval pathways**: When flagging risks, the agent should surface the **approval pathway** (ERMC, BU Head, Legal, Legal+Business) from the table above and the detailed text.
3. **Scope guard**: Agent should state that guidance applies only to **supply contracts** (Aerospace supplying goods) and that other agreement types are out of scope for the POC.
4. **Disclaimer**: Responses should remind that evaluations are for POC only and must be routed through Legal before commercial use.
