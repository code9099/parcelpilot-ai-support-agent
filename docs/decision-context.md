# Decision Context Schema & Fact Provenance

> This document defines how the agent orchestrator must construct the Decision Context
> that the LLM reasons over. The LLM never sees raw retrieval results or raw database
> rows — it reasons only over a curated, typed, pre-filtered evidence package.

---

## 1. Fact Provenance Types

Every fact presented in the Decision Context must carry an explicit provenance type.
A derived or user-stated fact must never be represented as though it came from the database.

| Type | Definition | Example |
|------|-----------|---------|
| `DATABASE_FACT` | A value retrieved directly from a database table (orders, tickets, accounts). Immutable at query time. | `ORD-1001.status = BOOKED` |
| `DOCUMENT_FACT` | A rule, policy, or term extracted from a PDF source document via vector search. Must include source file and section. | `SOP v4 §1: ₹250 fee after 30 min` |
| `USER_STATED_FACT` | Information provided by the user in their query. Not verified against the database unless explicitly cross-checked. | `"pickup was 5 hours late"` |
| `DERIVED_FACT` | A value computed from other facts. Must list the facts it was derived from. | `elapsed = 75 min (from booked_at and cancellation_requested_at)` |
| `EXPLICIT_CONTEXT_LINK` | The relationship is explicitly supplied as part of the request/test context. | `TKT-504 relates to ORD-1001 (supplied in context)` |
| `DETERMINISTIC_UNIQUE_MATCH` | A deterministic matching rule produces exactly one candidate. This is a match, not an immutable database fact. | `User says 'my ticket' + session has 1 active ticket` |
| `INFERRED_RELATIONSHIP` | The relationship is inferred by an LLM or semantic reasoning. Must not authorize consequential state-changing actions independently. | `LLM determines TKT-501 describes a bug affecting ORD-1001` |

### Provenance Rules

1. **A `DERIVED_FACT` must cite its inputs.** Example: `elapsed = 75 min` must cite `DATABASE_FACT booked_at=09:00` and `DATABASE_FACT cancellation_requested_at=10:15`.

2. **A `USER_STATED_FACT` must never be silently promoted to `DATABASE_FACT`.** If the user says "pickup was 5 hours late," this remains a `USER_STATED_FACT` even if an order in the database has a similar delay. If the system cross-checks and confirms it, the cross-check result is a separate `DATABASE_FACT` or `DERIVED_FACT`.

3. **A `DOCUMENT_FACT` must include the source file name, section reference, and `source_type`** (one of: `current_policy`, `deprecated_policy`, `current_sop`, `product_ops_guide`, `customer_agreement`).

4. **`deprecated_policy` facts must be tagged `authoritative: false`** and included only as historical context if relevant. They must never be the basis for a policy decision.

---

## 2. Decision Context Schema

The Decision Context is the structured evidence package passed to the LLM's final reasoning call. It is constructed by the orchestrator **before** the LLM sees it.

```
DecisionContext:
  session:
    account_id: string | null
    role: "customer" | "internal"
    plan: string  # resolved from accounts table

  query:
    original_text: string
    classified_intent: string  # e.g., "cancellation_query", "credit_query", "status_query"

  applicable_facts: [
    {
      fact: string
      type: DATABASE_FACT | DOCUMENT_FACT | USER_STATED_FACT | DERIVED_FACT
      source: string  # table name, file + section, "user query", or derivation inputs
      authoritative: boolean
      scope: string | null  # NORTHSTAR, LUMENWORKS, global, null
    }
  ]

  applicable_rules: [
    {
      rule_id: string  # e.g., "cancellation_booked_default"
      source_file: string
      source_section: string
      source_type: string  # current_policy, current_sop, customer_agreement, etc.
      is_deprecated: boolean
      customer_scope: string | null
      rule_text: string
      applies_to_this_query: boolean
      precedence_note: string | null  # e.g., "overridden by customer agreement §2"
    }
  ]

  evidence_gaps: [
    {
      missing_fact: string
      required_by: string  # which rule needs this fact
      impact: string  # what happens without it
    }
  ]

  computed_results: {
    # Deterministic calculations done BEFORE the LLM, not by it
    cancellation_eligible: boolean | null
    cancellation_fee_inr: number | null
    credit_eligible: boolean | null
    credit_amount_inr: number | null
    manager_approval_required: boolean | null
    sla_target: string | null
    sla_breach_status: "breached" | "not_breached" | "cannot_determine_without_business_hours_calendar"
  }

  context_only: [
    # Historical tickets, deprecated docs — explicitly labeled non-authoritative
    {
      fact: string
      type: string
      source: string
      authoritative: false
      warning: string  # e.g., "Historical resolution may be incorrect"
    }
  ]
```

---

## 3. Evidence Curation Pipeline

The orchestrator constructs the Decision Context using these steps **in order**, before the final LLM reasoning call:

### Step 1: Session Scope Filtering
- Inject `session.account_id` and `session.role` from server-side session
- All database queries filter by `account_id` for customer sessions
- Internal sessions have no account filter

### Step 2: Database Fact Retrieval
- Query structured data (orders, tickets, accounts) based on the classified intent
- Tag all results as `DATABASE_FACT`

### Step 3: Document Retrieval
- Vector search against the document store
- Tag results with `source_type`, `is_deprecated`, `customer_scope`

### Step 4: Deprecated Filtering (R1)
- Any result with `is_deprecated=true` is moved to `context_only`
- Never placed in `applicable_rules` as authoritative

### Step 5: Topic-Scoped Precedence (R2)
- For the specific topic of the query (cancellation, credits, SLA, etc.):
  1. Check if the session's customer agreement has a clause addressing this topic
  2. If the agreement clause **explicitly addresses and overrides** → it governs
  3. If the agreement clause **explicitly defers** (e.g., "use the current SOP") → use the current SOP/policy
  4. If the agreement is **silent** on this topic → use the current SOP/policy
  5. Product documentation is supplementary context (capabilities, known issues)
  6. Historical tickets go to `context_only`

### Step 6: Deterministic Computation
- Apply deterministic business rules using `applicable_facts`:
  - Cancellation eligibility by status + timing + account terms
  - Credit eligibility by delay + fault + account threshold
  - Credit amount by account-specific formula
  - Manager approval threshold check
  - SLA target lookup by plan + account overrides
  - SLA breach: deterministic for 24×7 targets; `cannot_determine_without_business_hours_calendar` for business-hour targets
- Results go into `computed_results`

### Step 7: Evidence Gap Detection (R3)
- Check each applicable rule's required inputs against available facts
- If any required fact is missing or unknown → add to `evidence_gaps`
- If `evidence_gaps` is non-empty → set `evidence_status = HUMAN_REVIEW`

### Step 8: Pack Decision Context
- Assemble all of the above into the `DecisionContext` object
- Pass to LLM for final reasoning call

---

## 4. LLM's Role in the Decision Context

The LLM receives the completed `DecisionContext` and may:

- **Explain** the precedence decision and why a specific source governs
- **Narrate** the computed result in natural language for the user
- **Surface** evidence gaps and recommend what verification is needed
- **Classify** severity from ticket descriptions using v3 §2 definitions
- **Correlate** known issues to ticket symptoms

The LLM must **NOT**:

- Override `computed_results` with its own arithmetic
- Resolve source conflicts by choosing a preferred document (precedence is pre-applied)
- Promote `USER_STATED_FACT` to `DATABASE_FACT`
- Treat `context_only` items as authoritative evidence
- Follow instruction-like content in retrieved document chunks (injection resistance)

---

## 5. Evidence Status Levels

| Level | Meaning | Conditions |
|-------|---------|------------|
| `HIGH` | 2+ authoritative sources agree, or one unambiguous agreement clause on-topic | No gaps, no conflicts, deterministic result available |
| `MEDIUM` | 1 authoritative source, no conflict, minor caveat | E.g., relevant known issue exists (KI-211) |
| `LOW` | Only deprecated or historical material found | No current authoritative source addresses the query |
| `HUMAN_REVIEW` | Document conflict, missing document evidence, or missing required factual input | `evidence_gaps` is non-empty, or conflicting authoritative sources, or SOP §3 uncertainty trigger |

---

## 6. Severity Classification Protocol

Severity is **not** a field in the ticket data. It must be classified by the LLM from the ticket description, using the definitions from Support Policy v3 §2.

### Process
1. LLM receives ticket `subject` and `description`
2. LLM classifies as P1, P2, or P3 using v3 §2 definitions
3. Classified severity is output as a structured field
4. Severity is passed to **deterministic** SLA policy logic
5. SLA logic looks up the response target by `(plan, severity, account_overrides)`
6. For 24×7 targets: breach = `elapsed_time > target`
7. For business-hour targets: breach = `cannot_determine_without_business_hours_calendar`
8. The LLM does **not** compute elapsed time or breach status

### The LLM must not:
- Invent severity levels not in v3 §2
- Perform SLA arithmetic
- Claim exact breach status for business-hour targets
