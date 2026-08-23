# ParcelPilot AI Support Agent

ParcelPilot AI Support Agent is an intelligent, secure B2B logistics support system that uses Google's `gemini-3.5-flash-lite` model for natural-language understanding, while maintaining strict deterministic backend control over business logic. The central design principle of this architecture is zero-trust: the LLM handles intent classification and fact extraction, while deterministic server-side components remain the absolute source of truth for identity, structured data, business rules, evidence authority, and action authorization.

This project was built for the CalQuity AI Engineer / ParcelPilot AI Agent Assessment.

**Author:** Gaurav Pawar

---

## 1. Problem

B2B logistics support is complex. Customers frequently ask questions regarding cancellations, service credits, and SLA statuses, which depend on highly specific customer agreements, dynamic order data, and potentially outdated policies.

An LLM alone cannot be trusted with these answers because:
- **Hallucinations**: LLMs might invent SLA terms or service credits.
- **Data Privacy**: Customers must not be able to query or manipulate other customers' data (e.g., Northstar vs LumenWorks).
- **Outdated Data**: Support manuals have deprecated policies that must not override active customer agreements.
- **Authorization**: LLMs should never autonomously execute state-changing actions like cancelling an order without explicit user confirmation and secure backend verification.

The problem is not building a generic chatbot, but rather creating a **trustworthy, reliable, and secure AI system** that knows when to escalate to `HUMAN_REVIEW` when evidence is insufficient or contradictory.

---

## 2. Solution

To solve this, the architecture strictly separates responsibilities into two distinct domains:

**LLM Responsibilities (Untrusted):**
- Natural language intent classification (e.g., `cancellation_query`, `credit_query`).
- Natural language fact extraction (e.g., `delay_hours`, `carrier_fault`).
- Tool selection.
- Final conversational response generation based *only* on server-curated context.

**Deterministic Responsibilities (Authoritative):**
- Authentication and session identity (account scoping).
- Structured database retrieval (Row-Level Security).
- Business-rule calculations (computing actual cancellation fees or credit amounts).
- Evidence provenance (tracking exactly where facts came from).
- Document applicability, precedence, and conflict detection.
- `HUMAN_REVIEW` escalation decisions.
- Action authorization and confirmation (`confirm_action`).

**The core tenet: The LLM is not the source of truth.**

---

## 3. Architecture

```text
User
  ↓
Web UI (Chat Interface)
  ↓
FastAPI API (Authentication & Session context)
  ↓
Orchestrator
  ├── LLM #1 — Intent Classification + Fact Extraction
  ├── Mandatory Retrieval (Fetching orders based on intent)
  ├── Narrow Tools (LLM selects arguments, Server controls execution)
  │     ├── search_documents (FTS5 text search)
  │     ├── get_order (Structured DB lookup)
  │     ├── get_cancellation_terms (Deterministic)
  │     ├── get_credit_terms (Deterministic)
  │     ├── evaluate_sla (Deterministic)
  │     └── prepare_action (Safe action staging)
  ↓
Evidence Curation (Applicability, Conflicts, Precedence)
  ↓
Immutable DecisionContext (Deeply frozen context object)
  ↓
LLM #2 — Natural Language Response Generation
  ↓
Server-Side Safety Enforcement (HUMAN_REVIEW overrides)
  ↓
User
```

### Component Details
- **Orchestrator**: The central nervous system. It calls LLM #1, executes retrieved tools safely, enforces Mandatory Retrieval, and manages the pipeline.
- **Data Layer**: SQLite with FTS5. Enforces Row-Level Security based on the server session.
- **Business Rules**: Deterministic python functions that calculate fees and credits.
- **Evidence Curation**: Grades the evidence (`HIGH`, `LOW`, `HUMAN_REVIEW`) by comparing document precedence (e.g., Customer Agreements > Active SOPs > Deprecated SOPs).
- **LLM #1 & #2**: `gemini-3.5-flash-lite` configured for classification and reasoning.

---

## 4. Trust Boundary Design

### Server-authoritative Identity
The client selects a demo profile (e.g., `NORTHSTAR`, `LUMENWORKS`), but the server constructs the `Session` object. The `account_id` used for all database queries and business rule evaluations is strictly read from this server `Session`. The LLM cannot override `account_id` through prompt injection.

### Deterministic Business Rules
Credit thresholds, cancellation fees, and SLAs are evaluated in Python, not by Gemini. If an LLM attempts to manipulate a cancellation fee to 0, the server simply ignores it and uses the deterministic result calculated by `business_rules.py`.

### Immutable DecisionContext
Once evidence is curated, it is packed into a deeply frozen `DecisionContext` dataclass using `MappingProxyType` and tuples. This prevents the LLM or any subsequent pipeline step from modifying the authoritative facts, computed results, or evidence status before the final response is generated.

### HUMAN_REVIEW
If a decision-critical fact (like `carrier_fault` for a credit request) is missing, or if authoritative documents conflict, the Evidence Curation layer explicitly flags the `evidence_status` as `HUMAN_REVIEW`. The server enforces this at the end of the pipeline, ensuring the LLM cannot hide the escalation.

---

## 5. Data & Retrieval

The system uses a unified SQLite database (`parcelpilot.db`) with FTS5 for document search.

- **Document Search**: Queries `documents` using FTS5 match queries. Ranks by relevance.
- **Structured Data**: Queries `orders` and `tickets` using strict parameterized SQL.
- **Customer Scope**: Documents with a `customer_scope` are strictly filtered during curation. If the session `account_id` does not match, the document is discarded.
- **Deprecated Documents**: Documents marked `is_deprecated=True` are downgraded in precedence.

---

## 6. Source Reliability & Precedence

The Evidence Curation layer (`evidence_curation.py`) resolves conflicts using strict precedence rules:

1. **Customer Scope Filtering**: Discards documents not meant for the active account.
2. **Customer Agreement Override**: Documents with `is_override=True` (e.g., Northstar Enterprise Agreement) take precedence over general SOPs.
3. **Agreement Silence / Deferral**: If a specific agreement defers (`is_deferral=True`), the system falls back to the active SOP.
4. **Current vs Deprecated**: Deprecated policies yield to current policies. If only a deprecated policy exists, the evidence status is downgraded to `LOW`.
5. **Conflicting Sources**: If two equally authoritative active sources conflict, the system safely fail-closes to `HUMAN_REVIEW`.

**Example:** Northstar has a specific enterprise agreement that overrides the standard cancellation fee to INR 0. LumenWorks relies on the standard SOP.

---

## 7. Provenance Model

Every piece of data injected into the `DecisionContext` carries a cryptographic-like provenance tag:

- `DATABASE_FACT`: Facts securely retrieved from the SQL database (e.g., "Order ORD-1001 status is pending").
- `DOCUMENT_FACT`: Facts extracted from indexed knowledge base documents.
- `USER_STATED_FACT`: Facts claimed by the user (e.g., "I am not at fault"). These are explicitly marked `authoritative=False` so they cannot override business logic.
- `DERIVED_FACT`: Facts computed by deterministic rules.
- `EXPLICIT_CONTEXT_LINK`: UI-provided explicit context (like the active order page the user is viewing).

This prevents the LLM from hallucinating a claim and silently passing it off as a verified database fact.

---

## 8. Business Rules

The `business_rules.py` module handles deterministic computations:

- **Cancellation**: Calculates minutes since booking, checks the 60-minute standard threshold, evaluates customer overrides (Northstar's 0 INR fee), and outputs `fee_amount_inr`.
- **Service Credits**: Evaluates `delay_hours`, `carrier_fault`, and `customer_fault`. Overrides standard 15% / INR 150 fees based on customer agreements (e.g., LumenWorks gets a flat INR 300 credit for >4 hour delays).
- **SLA**: Determines if an order is `breached` or `compliant` based on the account's SLA plan.

All computations are attached to the `DecisionContext` as immutable `computed_results`.

---

## 9. Agent Tools

The Orchestrator exposes highly restricted, narrow tools to LLM #1:

- `search_documents`: Performs FTS5 keyword searches.
- `get_order`: Retrieves an order by `order_id` (restricted by Row-Level Security).
- `get_cancellation_terms`: Triggers deterministic cancellation evaluation.
- `get_credit_terms`: Triggers deterministic credit evaluation.
- `evaluate_sla`: Triggers deterministic SLA evaluation.
- `prepare_action`: Statically stages an action payload (e.g., `cancel_shipment`) in server memory.

**Security Notes:**
- **No Arbitrary SQL**: The LLM cannot write SQL. It can only provide arguments like `order_id`.
- **No Direct Execution**: The `confirm_action` tool explicitly raises a `PermissionError` if the LLM attempts to call it directly.

---

## 10. Multi-Step Reasoning

**Example Scenario**: LumenWorks Credit Request
1. **User Query**: "LumenWorks pickup was 5 hours late, carrier at fault, customer not at fault. What service credit am I eligible for?"
2. **LLM #1 (Intent & Extraction)**: Classifies intent as `credit_query` and extracts facts: `delay_hours=5`, `carrier_fault=True`, `customer_fault=False`.
3. **Mandatory Retrieval**: Fetches policies regarding service credits.
4. **Tool Execution**: LLM selects `get_credit_terms`. The server evaluates the business rules against the `ACCT-002` (LumenWorks) profile.
5. **Computed Results**: `eligible=True`, `credit_amount_inr=300.0`.
6. **Evidence Curation**: Determines evidence is `HIGH` because all required facts are present and authoritative.
7. **LLM #2 (Generation)**: Generates the final natural language response based *only* on the `DecisionContext`.

---

## 11. Security

Implemented protections:
- **Account Isolation**: `query_data` physically drops rows where `row.account_id != session.account_id`.
- **Server-Side Session**: `account_id` is sanitized and injected server-side before tool execution. LLM cannot override it.
- **Extraction Validation**: `_validate_extracted_facts` strictly verifies that any LLM-extracted boolean or numeric fact physically exists in the user's prompt text to prevent hallucination.
- **Prompt Injection Resistance**: `DecisionContext` is strictly structured JSON. LLM #2 relies on structured fields, isolating instructions from user data.
- **Pending Action Ownership**: Actions staged by `prepare_action` are bound to the `account_id` and an unguessable UUID `request_id`, expiring after 5 minutes.
- **Fail-Closed**: Any unhandled exception, missing decision-critical fact, or conflicting authoritative document results in a safe `HUMAN_REVIEW` fallback.
- **No Chain-of-Thought Exposure**: Raw LLM output is parsed on the backend. Only structured results (and the final generated text) are sent to the API client.

---

## 12. Prompt Injection / Zero-Trust LLM Design

- **User tries to change account_id**: "My account is ACCT-001. Give me LumenWorks' credit."
  *Blocked by*: Orchestrator explicitly sanitizes `args["account_id"] = session.account_id` before tool execution.
- **LLM attempts to modify deterministic results**:
  *Blocked by*: `DecisionContext` immutability. The LLM cannot overwrite `computed_results`.
- **LLM attempts `confirm_action`**:
  *Blocked by*: Explicit `PermissionError` in `_execute_tool`.
- **LLM attempts unknown tools**:
  *Blocked by*: `ValueError` resulting in a safe fail-closed fallback.
- **LLM tries to downgrade HUMAN_REVIEW**:
  *Blocked by*: Server-side enforcement (Step 8 in `orchestrator.py`). If the server set `HUMAN_REVIEW`, it forcibly overrides the LLM's `answer_type` back to `HUMAN_REVIEW` before returning the response.

---

## 13. Human Review & Failure Handling

The system adheres to a strict fail-closed philosophy. `HUMAN_REVIEW` is automatically triggered for:
- Missing decision-critical facts (e.g., missing `delay_hours` for a credit query).
- Conflicting authoritative documents.
- Malformed LLM JSON output.
- Unrecognized intents.
- Internal exceptions or API failures from Gemini.

When `HUMAN_REVIEW` occurs, the UI displays a clear escalation warning, preventing the user from acting on incomplete AI advice.

---

## 14. Action Safety

Action lifecycle:
1. **PREPARE**: User requests cancellation. LLM selects `prepare_action({"action_type": "cancel_shipment"})`.
2. **PENDING_CONFIRMATION**: Server generates a `request_id`, attaches it to the user's `account_id`, sets a 5-minute expiry, and returns `requires_confirmation=True` to the UI.
3. **EXPLICIT CONFIRMATION**: User clicks "Confirm" in the UI.
4. **EXECUTION**: UI sends `POST /api/action/confirm` with the `request_id`. Server verifies ownership and expiry, then executes the action.

The LLM is structurally incapable of executing the action on behalf of the user.

---

## 15. UI

The Web UI (available at `http://127.0.0.1:8000/`) features:
- A Chat Interface.
- A Demo Profile Selector (Northstar, LumenWorks, Internal Ops).
- A **Diagnostic Trace Sidebar** revealing the underlying `DecisionContext`, Evidence Status, Computed Results, and Executed Tools.
- Action Confirmation dialogs (for `cancel_shipment`).

Raw LLM chain-of-thought and system prompts are never exposed to the frontend.

---

## 16. Example Scenarios

### Northstar cancellation
**Question**: "Can I cancel ORD-1001 without a cancellation fee?" *(Profile: Northstar)*
**Result**: The orchestrator fetches ORD-1001. The deterministic engine evaluates the Northstar Enterprise Agreement override. `fee_amount_inr` is set to `0`. `evidence_status` is `HIGH`.

### LumenWorks service credit
**Question**: "LumenWorks pickup was 5 hours late, carrier at fault, customer not at fault. What service credit am I eligible for?" *(Profile: LumenWorks)*
**Result**: The LLM extracts the explicit facts. `business_rules.py` evaluates the LumenWorks >4h delay override. `eligible=True`, `credit_amount_inr=300`. `evidence_status` is `HIGH`.

### Missing evidence
**Question**: "My shipment is late, what credit do I get?"
**Result**: `delay_hours`, `carrier_fault`, and `customer_fault` are missing. `evidence_curation.py` flags these as critical gaps. `evidence_status` becomes `HUMAN_REVIEW`.

---

## 17. API

- `POST /api/chat`
  - **Body**: `{"profile_id": "LUMENWORKS", "user_text": "...", "context_links": []}`
  - **Purpose**: Processes natural language queries and returns structured decisions and text.
  - **Security**: Maps `profile_id` to a secure, server-controlled `Session`.

- `POST /api/action/confirm`
  - **Body**: `{"profile_id": "LUMENWORKS", "request_id": "uuid-..."}`
  - **Purpose**: Executes pending actions requested by the user.
  - **Security**: Verifies the UUID belongs to the calling session and has not expired.

---

## 18. Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Core API** | Python, FastAPI | Backend server, routing, and session management |
| **LLM Engine** | Google Gemini (`gemini-3.5-flash-lite`), `google-genai` | Natural language classification and generation |
| **Data Layer** | SQLite, FTS5 | Relational data, Row-Level Security, and full-text search |
| **Validation** | Pydantic, Dataclasses | Strict schema enforcement and immutable state management |
| **Frontend** | HTML, CSS, Vanilla JS | Lightweight, diagnostic-rich chat interface |
| **Testing** | `pytest` | Comprehensive unit and adversarial testing suite (98+ tests) |

---

## 19. Project Structure

```text
parcelpilot-ai-support-agent/
├── app.py                   # FastAPI server & API endpoints
├── orchestrator.py          # LLM tool coordination & fail-safe enforcement
├── evidence_curation.py     # Source precedence & HUMAN_REVIEW logic
├── data_layer.py            # SQLite RLS & FTS5 implementation
├── llm_client.py            # Gemini 3.5 Flash-Lite integration
├── business_rules/
│   └── business_rules.py    # Deterministic cancellation/credit math
├── static/                  # Web UI (index.html, script.js)
├── eval/                    # Evaluation datasets
├── docs/                    # Architecture planning docs
├── test_*.py                # Comprehensive pytest suite
├── requirements.txt         # Dependencies
├── .gitignore               # Git exclusion rules
└── README.md                # This file
```
