# Knowledge Mapping Analysis: DOCX vs JSON

**Source DOCX:** `[RFP Tenders-LTAs] Contract Positions for POC_GB Legal_2026.02.19-v1.docx`  
**Current JSON:** `Contract_Positions_POC_GB_Legal_2026-02-19.json`

---

## 1. DOCX Structure (Actual Knowledge Document)

The DOCX contains a **table** with columns:

| Column | Content |
|--------|---------|
| **Sr No.** | 1–10 |
| **Clause** | Clause name |
| **Explanation** | Detailed guidance: entity tables, carve-outs, definitions, remarks |
| **Standard Positions** | Full clause text (Position 1, 2, 3 templates) or "GB's Ideal Position" |
| **Approval for Deviations** | Approval path, often with division-specific thresholds |

**Clauses 1–6** (general): "Explanation" + "Standard Positions" (Position 1, 2, 3 with full legal wording)  
**Clauses 7–10** (Aerospace Business Critical): "Original Position" + "Remarks" + "GB's Ideal Position"

---

## 2. JSON Structure (Current)

```json
{
  "meta": { "title", "source", "scope", "out_of_scope" },
  "clauses": [
    { "id", "name", "ideal_position", "approval_path", "keywords" }
  ]
}
```

Each clause has:
- **ideal_position**: One-line summary
- **approval_path**: One-line approval text
- **keywords**: Search terms for evidence matching

---

## 3. Mapping Gaps

### 3.1 ideal_position – Major Loss of Detail

| Clause | DOCX (Standard Positions / GB's Ideal) | JSON ideal_position |
|--------|--------------------------------------|---------------------|
| **1. Limitation of Liability** | Position 1–3: Full clause text (e.g. "Notwithstanding anything to the contrary... neither party shall be liable for: a. any losses which are consequential, special, indirect... b. any losses or damages for loss of profits... c. neither party's aggregate liability... will exceed 100% of the agreement value... d. the supplier shall have no liability for matters outside of the scope of works... e. the supplier shall have no liability where the same arises from any acts or omissions of client/end user.") | "Liability cap at 100% of Agreement/SOW value; consequential and indirect damages excluded, with approved carve-outs only." |
| **2. Governing Law** | Position 1: "This Agreement shall be governed by and construed in accordance with the laws of [•] excluding its conflicts of laws rules. The parties submit to the exclusive jurisdiction of courts at [•]." Plus entity table: GnB → India/Mumbai, India/Any other city, English law/Singapore, English Law/London | "Use approved governing law and jurisdiction combinations (e.g., India/Mumbai, approved alternatives)." |
| **3. Dispute Resolution** | Position 1–3: Full mediation + arbitration clauses (Indian Act, SIAC, LCIA, etc.) with seat, language, tribunal | "Arbitration preferred, with mediation where feasible; define arbitral rules, seat, language, and tribunal." |
| **4. Firm Price** | Position 1: "The Agreement price shall remain firm and fixed... for any reason other than: i. A change order... ii. Change in law... iii. Change in cost of raw material and other costs." Position 2–3: variants | "Firm/fixed pricing with limited escalation triggers (change order, change in law, raw material changes)." |
| **5. Force Majeure** | Position 1: Full ICC-style FM clause; para 4: "Force Majeure cannot be considered as an excuse for non-payment of goods already delivered... no Party shall be entitled to rely on... lack of funds due to any commercial, economic or financial reason" | "FM includes uncontrollable events; no FM excuse for payment of delivered goods/services; exclude economic hardship." |
| **6. Liquidated Damages** | Position 1: "at rate of half (0.5%) percent of the delayed value of Goods for every week of delay... subject to a maximum limit of five (5) percent of the Agreement price. LD shall be applicable only if the delay is arising solely due to default on part of Supplier." Position 2: similar | "LD should be on delayed value, with clear rate/cap and exclusive-remedy language; avoid penalty framing." |
| **7. Orders Extending Beyond Termination** | "Termination of the Agreement terminates all in-effect Orders unless Parties expressly agree otherwise via a mutually signed addendum. If any Order's delivery period extends beyond the Term, Parties may renegotiate prices for the residual period." | "Termination generally terminates in-effect orders unless mutually agreed otherwise; permit repricing for overhang orders." |
| **8. Quantity Protection** | "if PO quantity deviates beyond +/-20% of forecast, GB is reimbursed at actuals for raw material, WIP and finished goods on valid documentation. Forecasts do not trigger procurement/capex; when within lead time, forecasts convert to firm POs." | "Forecast deviations beyond +/-20% trigger reimbursement at actuals; forecasts within lead time convert to firm POs." |
| **9. Inventory Requirements** | "Inventory against non-binding forecasts limited to a maximum of 4 weeks of RM/FG once forecast enters lead time." | "Inventory against non-binding forecasts capped (e.g., max 4 weeks RM/FG once forecast enters lead time)." |
| **10. Change Orders Procedure** | "No changes implemented without a signed Change Order capturing price/time impact. GB entitled to equitable adjustment at actuals (including supplier cancellation charges, requalification/FAI, tooling/NRE, logistics) and schedule relief tied to critical path." | "No change implemented without signed change order; capture time/price impact and equitable adjustment at actuals." |

**Issue:** The JSON keeps only a short summary. The DOCX has full clause templates and richer wording that could be used for redline suggestions and comments.

---

### 3.2 Explanation – Not in JSON

The DOCX "Explanation" column contains:

- **Clause 1:** GnB liability cap rules, carve-outs (breach of law, criminal act, gross negligence, etc.), Consequential Loss definition (a–k), Indian law note
- **Clause 2:** Entity → Governing Law / Jurisdiction table (GnB → India/Mumbai, India/other city, English law/Singapore, English Law/London)
- **Clause 3:** Arbitration preferences, mediation, LCIA/SIAC/ICC table
- **Clause 4:** Client expectations, escalation triggers (expiry, delay not attributable to GnB, change in law, raw material)
- **Clause 5:** FM definition, notice, payment exclusion, Economic Hardships exclusion, 120-day joint decision
- **Clause 6:** LD intent, scope (delay in supply, documentation, etc.), cap, exclusive remedy, delayed value
- **Clauses 7–10:** Original Position + Remarks

**Issue:** None of this is in the JSON. It would help risk rationale, counterfactuals, and RAG retrieval.

---

### 3.3 Approval – Simplified and Division-Specific Lost

| Clause | DOCX Approval | JSON approval_path |
|--------|---------------|--------------------|
| 1 | "Exceeds 100% of Contract Value – ERMC approval required" | "ERMC approval required if liability exceeds 100% of contract value." |
| 2 | "Any other governing law, other than mentioned in explanation – BU Head" | "BU Head for governing law outside approved combinations." |
| 3 | "Legal Team to decide" | "Legal Team to decide." |
| 4 | "ERMC if Term > 2 Years / Value > 25cr." | "ERMC if term > 2 years or contract value > 25cr." |
| 5 | "Legal team in consultation with Business Team." | Same |
| 6 | "Division → ERMC Approval. Aerospace, Appliances (Sales), Interio, Locks, PED, PES, SSD, Tooling. → When LD is more than 10%. Construction, E&E (MEP & Pire), SSG, GITL. → When LD is more than 5%" | "ERMC based on division thresholds when LD exceeds approved limits." |

**Issue:** Division-specific LD thresholds (10% vs 5%) are lost in the JSON.

---

### 3.4 Multiple Positions – Not Represented

Clauses 1–6 have **Position 1, 2, 3** (different clause variants). The JSON has a single `ideal_position`. The system cannot choose between positions or expose alternatives.

---

### 3.5 Keywords – Hand-Picked vs DOCX Vocabulary

The JSON keywords are manually chosen. The DOCX Explanation and Standard Positions contain additional terms (e.g. "notwithstanding", "SOW", "carve-out", "GnB", entity names) that could improve evidence matching.

---

## 4. Summary of Misalignment

| Aspect | DOCX | JSON | Gap |
|--------|------|------|-----|
| ideal_position | Full clause text (Position 1–3) or GB's Ideal paragraph | One-line summary | Major – full wording lost |
| Explanation | Detailed guidance, tables, definitions | Not present | Not mapped |
| Approval | Sometimes division-specific | Simplified | Division thresholds lost (e.g. LD) |
| Multiple positions | Position 1, 2, 3 | Single ideal | No variant support |
| Scope / out_of_scope | In preamble | In meta | Largely aligned |
| Clause names | Match (minor punctuation) | Match | OK |

---

## 5. Recommendations

1. **Regenerate JSON from DOCX**  
   - Parse the DOCX table (e.g. with python-docx)  
   - Map: Clause name, Explanation, Standard Positions (or GB's Ideal), Approval  
   - Store full clause text in `ideal_position` or a new `standard_positions` array  
   - Preserve division-specific approval where present  

2. **Extend JSON schema**  
   - `explanation`: Text from Explanation column  
   - `standard_positions`: Array of { "label": "Position 1", "text": "..." }  
   - `approval_detail`: Full approval text (including division table for LD)  
   - `keywords`: Enriched from Explanation + Positions  

3. **Update consumers**  
   - Agent1: Use `standard_positions[0].text` or `ideal_position` for assessment  
   - Redline DOCX: Prefer full clause text for suggested edits when available  
   - RAG: Index Explanation + Standard Positions for retrieval  

4. **Automation**  
   - Add a script (e.g. `scripts/sync_knowledge_from_docx.py`) to parse the DOCX and output/update the JSON so the mapping stays in sync when the source document changes.
