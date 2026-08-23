---
name: calquity-spec
description: Hard constraints for the CalQuity Agent build
---
# CalQuity Agent Specification Constraints

Build against build_spec.md as ground truth. Hard constraints, no exceptions:
- No LangGraph or any agent framework — explicit tool-calling loop only.
- No generic query_data(query_type, params) interface — named tools only (get_order, get_cancellation_terms, get_credit_terms, etc.)
- confirm_action is NEVER an LLM-callable tool. It's a plain backend endpoint the frontend calls after a human clicks Confirm. The model must never see it in its tool list.
- Session scope uses account IDs (ACCT-001/ACCT-002), never customer names, and is server-injected — never accept an account_id argument from the model.
- Account-specific overrides (cancellation waiver, credit terms, response times) live in a config dict (ACCOUNT_TERMS), never as if/elif branches on account_id.
- If any part of this spec seems wrong or infeasible, stop and tell me — do not silently change or skip it.
- Never edit a test's expected value to make it pass. If a test fails, fix the code or flag that the spec's expectation is wrong.
