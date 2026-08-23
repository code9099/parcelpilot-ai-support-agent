# Open Questions — Genuine Unresolved Source Limitations

> This document lists ONLY issues that cannot be resolved from the supplied source data.
> All other ambiguities from the source-of-truth report have been resolved by human decisions
> documented in the eval fixtures and decision-context schema.

---

## 1. Business Hours Calendar — UNDEFINED

**Status**: Unresolvable from supplied sources

**Problem**: Support Policy v3 §3 references "business hours" and "business days" as units for SLA targets. LumenWorks Agreement §1 adds "No weekend or after-hours support coverage." No document in the assessment pack defines:
- What hours constitute "business hours" (e.g., 9am–6pm?)
- What timezone business hours are measured in
- What days constitute "business days" (e.g., Mon–Fri?)
- Whether Indian public holidays are excluded

**Impact on implementation**:
- **24×7 targets** (Northstar P1, Enterprise P1 default): Breach calculation is fully deterministic — elapsed wall-clock time vs. target.
- **Business-hour/business-day targets**: Exact breach status **cannot be computed**. The system must report the target and the elapsed wall-clock time, and flag breach status as `cannot_determine_without_business_hours_calendar`.

**What the system must NOT do**: Invent a working-hours calendar (e.g., assume 9am–6pm IST Mon–Fri) and present computed breach status as authoritative.

**Decision applied**: Per decision #5, the system represents business-hour breach checks as requiring human verification.

---

## 2. No LumenWorks PICKED_UP Order

**Status**: Low impact — no eval case requires it

**Problem**: Build_spec §8 stated a need for "a BOOKED-not-picked-up order and a PICKED_UP order at minimum, for both Northstar and LumenWorks." The data pack contains:
- Northstar: ORD-1001 (BOOKED) ✅ and ORD-1002 (PICKED_UP) ✅
- LumenWorks: ORD-2001 (BOOKED) ✅ and ORD-2002 (BOOKED) ✅ — **no PICKED_UP order**

**Impact on implementation**: Minimal. No eval case tests a LumenWorks PICKED_UP cancellation scenario. The rule for PICKED_UP is the same regardless of account: SOP v4 §1 says "Do not cancel. Use the return-to-origin workflow." LumenWorks Agreement §2 defers to SOP, so the behavior would be identical to the default.

**If tested**: The agent should apply SOP v4 §1 (return-to-origin), and the LumenWorks agreement does not override this.

---

## 3. No DRAFT Order in Data Pack

**Status**: Low impact — no eval case tests it

**Problem**: SOP v4 §1 defines DRAFT cancellation (free, no fee), but no order in the data pack has `status = DRAFT`.

**Impact on implementation**: The cancellation logic must handle the DRAFT status path (trivially: free cancel with no fee). No eval fixture tests this directly, but the rule is simple and deterministic.

---

## 4. Monthly Aggregate Credit Cap Tracking

**Status**: Implementation design question

**Problem**: Northstar Agreement §3 specifies a monthly aggregate credit cap of ₹5,000. The data pack provides individual orders but no cumulative credit history. There is no way to determine from the data pack alone how much credit has already been issued to Northstar in the current month.

**Impact on implementation**: The system can compute individual credit amounts and flag the ₹5,000/month cap in responses, but cannot verify whether the cap has been reached without tracking cumulative credits over time.

**Recommendation**: Surface the cap in agent responses (e.g., "Note: Northstar has a ₹5,000 monthly aggregate credit cap per their agreement") but do not claim the cap is or isn't reached without cumulative data.

---

## 5. Ticket-to-Order Linking

**Status**: No explicit foreign key

**Problem**: Tickets do not have an `order_id` field. Some tickets implicitly relate to orders:
- TKT-504 (SwiftShip status lag) relates to ORD-1001 (same account, SwiftShip, BOOKED)
- TKT-501 (shipment creation failing) is platform-wide for ACCT-001, not order-specific

**Impact on implementation**: Ticket-to-order associations must be resolved through explicit context or deterministic candidate matching (e.g., exact account + carrier + temporal proximity) before falling back to LLM inference. Absence of a foreign key does not mean LLM inference is mandatory.

---

## 6. KI-208 Threshold Precision

**Status**: Minor ambiguity

**Problem**: Product Ops Guide describes KI-208 failures "above approximately 3,000 rows." The word "approximately" means the exact failure threshold is not deterministic. TKT-451 (historical, 3,500 rows failed) and TKT-502 (current, 4,200 rows fails at ~70%) are consistent with this range but don't pin an exact boundary.

**Impact on implementation**: When advising customers about bulk upload, the agent should cite the workaround (split below 3,000 rows) and the official supported limit (5,000 rows), noting the known issue. It should NOT state "3,000 is the actual limit" — that was the incorrect resolution in TKT-451.
