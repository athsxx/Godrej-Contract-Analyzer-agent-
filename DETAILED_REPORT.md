# Aerospace Contract Analyzer - Detailed Architecture Report

## 1. Project Overview & Purpose
The **Aerospace Contract Analyzer** (`contractual_scaffolding`) is a Django-based web application designed to automatically parse, analyze, and assess the risk of engineering and procurement contracts. It uses a multi-agent AI architecture to extract specific commercial clauses and flag deviations from standard company policy, presenting the results in a Red-Amber-Green (RAG) risk table.

## 2. High-Level Architecture
The system is built on a Django backend and utilizes Large Language Models (LLMs) via AWS Bedrock (with a local LLM fallback). The core logic is split into two specialized "agents" that work sequentially to ensure accurate grounding and risk assessment.

*   **Django Web Layer (`guru/views.py`)**: Handles the user interface, file uploads (PDFs/DOCXs), session management, chat interactions, and exports (CSV, detailed DOCX reports).
*   **Agent 1 - Clause Extractor (`agent1_clause_analyzer.py`)**: The data extraction engine. It reads the contract, chunks the text, and searches for specific evidence of 14 predefined commercial clauses.
*   **Agent 2 - Risk Reviewer (`agent2_reviewer.py`)**: The policy engine. It takes the output from Agent 1, evaluates the responses against company baseline expectations, assigns RAG status, and attaches standardized rationales and mitigation strategies.

## 3. Detailed Process Flow

1.  **Document Ingestion & Hierarchy Processing**:
    *   The user uploads a set of contract documents.
    *   Agent 1 respects a strict priority hierarchy for resolving conflicts: **PO (Purchase Order) > SPC (Special Purchase Conditions) > GPC (General Purchase Conditions) > TERMS (Other attachments)**.
    *   The documents are parsed and chunked. Agent 1 uses a "smart sampling" algorithm (`_sample_segments`) to prioritize chunks containing critical keywords (e.g., "liquidated", "damage", "advance", "liability").

2.  **Clause Extraction (Agent 1)**:
    *   Agent 1 operates against a hardcoded `CLAUSE_SPEC` containing 14 key areas, including:
        *   Payment Terms (e.g., 45% Minimum Advance)
        *   Liquidated Damages (LD) (Max 5%)
        *   Cancellation Clause (Early Termination Fees)
        *   Governing Law & Arbitration
    *   The LLM is prompted to strictly extract JSON evidence for each sub-item.
    *   It must output a status metric (`Yes`, `No`, `Partial`, or `NA`), a short quote of evidence, and the exact citation mapping (file, section, page). The agent is explicitly instructed to omit sub-items if no explicit evidence is found to prevent hallucination.

3.  **Risk Assessment & RAG Generation (Agent 2)**:
    *   Agent 2 receives the structured JSON output from Agent 1.
    *   It filters for items that are not fully compliant (i.e., not a strict "Yes").
    *   It assigns a risk color:
        *   🟥 **Red**: Status is "No" (explicitly rejected/non-compliant).
        *   🟧 **Amber**: Status is "Partial" or "NA" (partially compliant or unknown).
        *   🟩 **Green**: Status is "Yes" (fully compliant).
    *   It looks up standardized explanations in `rationale_mitigation.txt` using semantic matching on the clause name. It retrieves the "Rationale" (why this clause matters) and the "Mitigation Strategy" (how to negotiate or proceed).

4.  **Presentation & Export**:
    *   The final output is presented to the user via the Django frontend as a Markdown-formatted table.
    *   The user can chat with the system to ask counterfactuals or specific questions.
    *   The user can export the analysis to a generated Word document (`reviewed_contract.docx`) or download the raw data via CSV exports (`clause_analysis.csv`, `mitigation_checklist.csv`).

## 4. Key Files & Responsibilities

| File | Subsystem | Responsibility |
| :--- | :--- | :--- |
| `agent1_clause_analyzer.py` | LLM Extraction | Defines `CLAUSE_SPEC`. Handles AWS Bedrock API calls (supporting Anthropic, Llama, and Nova models). Implements chunking guardrails and LLM prompting for JSON-first evidence extraction. |
| `agent2_reviewer.py` | Risk Assessment | Parses Agent 1's output. Applies the RAG (`🟩`, `🟧`, `🟥`) logic. Cross-references identified risks with `rationale_mitigation.txt` to provide actionable negotiation advice. |
| `guru/views.py` | Presentation (Django) | Contains the endpoint `workspace_aerospace_contract_analyzer`. Manages the session state, file upload/removal actions, and file download responses (DOCX/CSV). |
| `rationale_mitigation.txt` | Knowledge Base | A text file containing the baseline company rationale and recommended mitigation strategies for standard clause deviations. |
| `agents/sample_agent/chat_agent.py` | Orchestration | (Referenced by views) The main controller that glues the UI to the underlying agents, managing the file system storage (`UPLOAD_ROOT`) per session key. |
