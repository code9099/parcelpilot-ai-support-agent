# Verified Business Rules — Source of Truth

> All rules in this document are extracted verbatim or paraphrased directly from the 6 assessment PDFs and the Excel data pack.
> No rules have been invented, inferred, or extended beyond the source material.
> Snapshot date: **2026-08-16 11:00 Asia/Kolkata** | Currency: **INR**

---

## 1. Source Precedence (R2)

**Source**: Support Policy v3 §1
**Exact text**: "When sources conflict, use the signed customer agreement first, then the current support policy, then current product documentation. Historical tickets and internal notes are context only and may contain incorrect past guidance."

**Application**: Per-topic, not per-document. A single customer agreement may override on one topic and defer on another.

**Evidence from source data**:
- LumenWorks Agreement §2 (cancellation) **defers** to SOP
- LumenWorks Agreement §3 (credits) **overrides** SOP
- Same document, two different precedence outcomes on two topics

---

## 2. Deprecated Source Filtering (R1)

**Source**: Support Policy v2 header
**Exact text**: "Status: DEPRECATED - DO NOT USE FOR CURRENT REQUESTS... This file is intentionally retained for historical reference and must not be used as current policy."

**Rule**: Any document with `is_deprecated=true` is never authoritative. v2 is fully superseded by v3 — same structure, same topic coverage. No exception cases exist in this dataset.

---

## 3. Cancellation Rules

### 3.1 Global Defaults (SOP v4 §1)

| Order Status | Rule | Fee |
|-------------|------|-----|
| **DRAFT** | May be cancelled | No fee |
| **BOOKED** (not PICKED_UP), ≤30 min since booking | May be cancelled | No fee |
| **BOOKED** (not PICKED_UP), >30 min since booking | May be cancelled | ₹250, unless agreement explicitly waives |
| **PICKED_UP** | Do not cancel | N/A — use return-to-origin workflow |
| **DELIVERED** | Cannot be cancelled | N/A |

### 3.2 Northstar Override (Agreement §2)

**Exact text**: "Northstar may cancel any BOOKED shipment before pickup with no cancellation fee, regardless of how long ago the shipment was booked. Once a shipment is PICKED_UP, the standard return-to-origin process applies."

| Status | Northstar Behavior | Differs from Default? |
|--------|--------------------|-----------------------|
| BOOKED (not picked up) | **No fee regardless of time** | **YES** — waives the ₹250 after-30-min fee |
| PICKED_UP | Return-to-origin | No |

### 3.3 LumenWorks (Agreement §2)

**Exact text**: "No special cancellation-fee waiver applies. Use the current ParcelPilot Cancellation & Service Credit SOP."

| Status | LumenWorks Behavior | Differs from Default? |
|--------|---------------------|-----------------------|
| All statuses | **SOP v4 defaults apply in full** | **No override** |

### 3.4 ACCT-003, ACCT-004

No customer agreement exists. SOP v4 defaults apply for all statuses.

---

## 4. Service Credit Rules

### 4.1 Global Default Eligibility (SOP v4 §2)

All three conditions must be met:
1. Pickup is **more than 2 hours** past the end of the scheduled pickup window
2. **Carrier is at fault** (`carrier_fault == true`)
3. **No customer-caused issue** (`customer_fault == false`)

### 4.2 Global Default Credit Amount (SOP v4 §2)

**Exact text**: "The default credit is the lower of INR 500 or 10% of the shipment fee."
**Formula**: `min(500, shipment_fee_inr × 0.10)`

### 4.3 Agreement May Override (SOP v4 §2)

**Exact text**: "A signed customer agreement may replace the default delay threshold, credit amount, or cap."

### 4.4 LumenWorks Override (Agreement §3)

**Exact text**: "If a pickup is more than 4 hours past the end of the scheduled pickup window, the carrier is at fault, and the customer is not at fault, LumenWorks receives a fixed INR 300 service credit. This clause replaces the default failed-pickup credit amount and timing threshold in the SOP."

| Parameter | SOP Default | LumenWorks Override |
|-----------|-------------|---------------------|
| Delay threshold | 2 hours | **4 hours** |
| Credit amount | min(₹500, 10% of fee) | **Fixed ₹300** |
| Carrier fault required | Yes | Yes (unchanged) |
| No customer fault required | Yes | Yes (unchanged) |

### 4.5 Northstar (Agreement §3)

**Exact text**: "Monthly aggregate service credits are capped at INR 5,000. Unless this agreement states otherwise, the current ParcelPilot service-credit SOP applies."

| Parameter | SOP Default | Northstar Override |
|-----------|-------------|-------------------|
| Delay threshold | 2 hours | **No override** — 2 hours applies |
| Credit amount | min(₹500, 10% of fee) | **No override** — SOP formula applies |
| Monthly aggregate cap | Not defined in SOP | **₹5,000/month** (new constraint) |

### 4.6 Manager Approval (SOP v4 §3)

**Exact text**: "Any individual credit above INR 1,000 requires manager approval."
**Threshold**: Strictly greater than ₹1,000.

> [!NOTE]
> Under the default formula `min(500, fee × 10%)`, the maximum possible credit is ₹500. This threshold cannot be exceeded via the default formula alone. It can only be triggered by (a) a custom agreement term specifying a higher amount, or (b) a manually proposed credit. Neither exists in the current data pack.

### 4.7 Uncertainty Prohibition (SOP v4 §3)

**Exact text**: "Do not promise a credit when carrier fault, pickup timing, or customer fault is unknown."

### 4.8 Data Conflict (SOP v4 §3)

**Exact text**: "When data conflicts, identify the conflict and request verification before a state-changing action."

---

## 5. SLA / Response Time Rules

### 5.1 Current Defaults (Support Policy v3 §3)

| Plan | P1 | P2 | P3 |
|------|----|----|-----|
| Enterprise | 30 minutes, 24×7 | 2 hours | 1 business day |
| Growth | 2 business hours | 4 business hours | 2 business days |
| Standard | 4 business hours | 1 business day | 2 business days |

### 5.2 Deprecated Values (Support Policy v2 — DO NOT USE)

| Plan | P1 | P2 | P3 |
|------|----|----|-----|
| Enterprise | 1 hour | 4 hours | 2 business days |
| Growth | 4 business hours | 1 business day | 3 business days |
| Standard | 8 business hours | 2 business days | 3 business days |

### 5.3 Northstar Override (Agreement §1)

**Exact text**: "For Northstar Logistics, the following first-response targets replace ParcelPilot's standard support-policy targets"

| Severity | Northstar Target | Enterprise Default | Override? |
|----------|-----------------|-------------------|-----------|
| P1 | **15 minutes, 24×7** | 30 minutes, 24×7 | **Yes** |
| P2 | **1 hour** | 2 hours | **Yes** |
| P3 | **8 business hours** | 1 business day | **Yes** |

### 5.4 LumenWorks (Agreement §1)

| Severity | LumenWorks Target | Growth Default | Override? |
|----------|-------------------|----------------|-----------|
| P1 | 2 business hours | 2 business hours | **No** (identical) |
| P2 | 4 business hours | 4 business hours | **No** (identical) |
| P3 | 2 business days | 2 business days | **No** (identical) |
| **Additional** | **No weekend or after-hours support coverage** | Not stated | **Yes** (restriction) |

### 5.5 Business Hours — UNDEFINED

No source document defines the boundaries of "business hours" or "business days" (e.g., 9am–6pm IST, Mon–Fri). For 24×7 targets, breach calculation is deterministic. For business-hour/business-day targets, exact breach status cannot be computed and must be represented as requiring human verification.

---

## 6. Severity Definitions (Support Policy v3 §2)

| Severity | Definition |
|----------|-----------|
| **P1 — Critical** | Complete production outage preventing all shipment creation for a customer, confirmed security incident or suspected credential exposure, or another event causing immediate material business risk with no workaround. |
| **P2 — High** | Major feature unavailable or materially degraded for a customer, but core operations remain possible or a workaround exists. |
| **P3 — Normal** | Minor defect, how-to question, configuration request, or issue with limited operational impact. |

**Classification method**: LLM classifies severity from ticket description using these definitions. The LLM does not perform SLA arithmetic — classified severity is passed to deterministic SLA policy logic.

---

## 7. Escalation (Support Policy v3 §4)

**Exact text**: "P1 incidents should be escalated immediately. If a response target is already breached, the agent should clearly state the breach and recommend escalation rather than hiding uncertainty."

---

## 8. Known Issues

| ID | Issue | Status | Source |
|----|-------|--------|--------|
| **KI-208** | Bulk Upload failures on CSVs above ~3,000 rows (supported limit is 5,000) | **Investigating** | Product Ops Guide §2 |
| **KI-211** | SwiftShip pickup webhooks can arrive up to 20 min late; parcel may be collected while showing BOOKED | **Monitoring** | Product Ops Guide §2 |
| **KI-176** | Address validation | **Resolved** (18 Jul 2026) | Product Ops Guide §3 |

**KI-176 guidance**: "Do not use this resolved issue to explain new incidents unless evidence specifically matches it."

---

## 9. Historical Ticket Resolutions — Context Only

**Source**: Excel README: "Some historical ticket resolutions may be incorrect. Treat them as historical context, not policy authority."

**Source**: Support Policy v3 §1: "Historical tickets and internal notes are context only and may contain incorrect past guidance."

| Ticket | Resolution Given | Actually Correct? | Error |
|--------|-----------------|-------------------|-------|
| TKT-450 | ₹250 fee applied to Northstar after 30 min | **NO** | Northstar Agreement §2 waives fee regardless of time |
| TKT-451 | Growth plan only supports 3,000 rows | **NO** | Product Ops Guide §1: limit is 5,000 rows. KI-208 is a bug, not a plan limit |

---

## 10. Account Mapping

| Account ID | Name | Plan | Agreement | Premium Support |
|------------|------|------|-----------|-----------------|
| ACCT-001 | Northstar Logistics | Enterprise | YES — PDF 05 | Yes |
| ACCT-002 | LumenWorks | Growth | YES — PDF 06 | No |
| ACCT-003 | Beacon Retail | Standard | NO | No |
| ACCT-004 | Axis Labs | Enterprise | NO | No |

### Account Terms Summary (for config dict)

```
ACCT-001 (Northstar):
  cancel_waiver: true  (any BOOKED, no fee, regardless of time)
  credit_threshold_hours: 2  (SOP default — agreement doesn't override)
  credit_calc: "default"  (min(500, fee × 0.10))
  monthly_credit_cap: 5000
  sla_overrides: {P1: "15 min 24x7", P2: "1 hour", P3: "8 business hours"}

ACCT-002 (LumenWorks):
  cancel_waiver: false  (agreement explicitly defers to SOP)
  credit_threshold_hours: 4  (agreement overrides SOP default of 2)
  credit_calc: "fixed_300"  (agreement overrides SOP formula)
  monthly_credit_cap: null  (no cap stated)
  sla_overrides: {weekend_afterhours: false}
  sla_note: "P1/P2/P3 values match Growth defaults; no numeric override"

Default (ACCT-003, ACCT-004, any account without agreement):
  cancel_waiver: false
  credit_threshold_hours: 2
  credit_calc: "default"  (min(500, fee × 0.10))
  monthly_credit_cap: null
  sla_overrides: null  (use plan-level defaults from v3 §3)
```
