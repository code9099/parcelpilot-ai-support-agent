# Architecture Note

## 1. Agent Design
The system uses a two-stage LLM orchestrator combined with a deterministic rule engine. LLM #1 is strictly constrained to classifying intents and extracting parameters into structured JSON. The output is deterministically validated and passed to a deterministic rules engine (Python functions) that queries the database, applies business logic, and calculates exact numbers based on agreements and SOPs. LLM #2 receives the output of this engine in an immutable `DecisionContext` and uses it to construct a human-readable response without performing any core reasoning itself.

## 2. Tool Design
The tools exposed to the LLM are designed for exact mapping of business processes (cancellation, service credit, SLA). The system strictly denies tools from mutating data directly. `prepare_action` creates a staged `PendingAction` that requires explicit UI interaction to confirm via a separate, LLM-blocked `confirm_action` endpoint, ensuring that LLMs can never unilaterally perform destructive or irreversible actions. 

## 3. Data & Retrieval
Data is dual-sourced: 
- Relational structured data (SQLite) handles account schemas, orders, and real-time states.
- Semantic knowledge (FTS5) handles unstructured knowledge from PDFs. Documents are chunked contextually and enriched with metadata (deprecation status, scope, source type).

Retrieval is context-aware. If the session role is a customer, retrieval enforces strict tenant isolation, excluding competing customer agreements from the context window entirely.

## 4. Reliability & Conflict Handling
The system handles source conflicts explicitly rather than relying on prompt engineering. This precedence rule is not invented—it is quoted directly from Support Policy v3 §1: "use the signed customer agreement first, then the current support policy, then current product documentation." The deterministic engine prioritizes structured constraints derived from customer agreements over default SOPs, guaranteeing consistent compliance with negotiated contracts regardless of LLM variability.

## 5. Access Control
Access control is enforced at the deterministic boundary, not the LLM boundary. The LLM's inputs (session role and account_id) are derived strictly from the backend FastAPI session context and cannot be overridden by client prompt injection. Tools inherently filter all data queries to the active `account_id` if the user is a `customer`, while allowing full cross-tenant visibility for the `internal` role.

## 6. Trade-offs
- **Single LLM Provider:** The system currently relies on Gemini 2.5 Flash without a fallback provider, which is a single point of failure.
- **Latency vs. Correctness:** Using two LLM calls plus a deterministic execution step in between introduces latency but was chosen to absolutely guarantee mathematical correctness and security over speed.
- **Deterministic Rigidity:** The system fails closed (escalating to HUMAN_REVIEW) heavily when information is missing or contradictory, preferring caution over helpfulness.
