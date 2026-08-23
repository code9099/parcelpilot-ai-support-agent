# Execution & Submission Checklist

Companion to build\_spec.md — this covers process, not architecture.

---

## 0. Exact submission requirements (confirmed from the actual JD, not inferred)

Submission form: **https\://forms.gle/hLGBrDrNRmK7UAbv6** — open it now and check the actual fields (file upload vs. link, character limits) before hour 9, not after you've recorded a video in the wrong format.

Six things required, and two of them aren't in build\_spec.md yet:

1. **Repository — public, required, not "nice to have."** The JD says "a link to the code repository (public repo) with clear setup and run instructions." This is firmer than "hosted app," which is only "highly preferred." Make sure the repo is actually public before submitting, and that setup/run instructions are real — §5 below already covers this.
2. **Hosted application** — URL if available, matches what's already planned.
3. **Demo video**, \~5 min: architecture, working demo, key decisions. Matches build\_spec.md §7.
4. **Architecture note**: agent design, tool design, document/structured-data handling, source reliability/conflict handling, major trade-offs. Matches the 6-section structure already locked (access control was an addition beyond the JD's 5, which is fine — it's not missing anything, just more specific).
5. **Product note — four required components, not three.** "Which additional client problem you chose and how you addressed it" (singular — say plainly you chose Problem 2, Trust & Reliability, as the one baked into core architecture; Problem 1, Proactive Detection, is either the lightweight stretch feature or explicitly listed under "what I'd build next" depending on how Day 2 goes), "anything else you'd build," "what you intentionally left out" (the cuts table in build\_spec.md §5 already covers this), and — **new, not yet addressed anywhere in the spec** — **"one metric you would use to judge whether the product is useful."**

   Worth actually thinking through rather than filling in a generic answer: raw "resolution rate without escalation" can be gamed by answering confidently and wrong, which is the exact failure mode this whole build is designed against. The metric that's actually consistent with the thesis: **correct-and-resolved rate** — the percentage of queries answered directly (not escalated) where the answer is verified correct — tracked alongside **escalation precision** (of the queries that were escalated, what fraction genuinely needed a human, vs. the system being uselessly over-cautious). Proposing one metric with that paired guardrail is a stronger answer than either "resolution rate" alone (rewards confident wrong answers) or "user satisfaction" (lagging, hard to attribute).
6. **AI Tool Usage — new, not yet addressed anywhere.** "Briefly state which AI coding tools you used and how you used them." Given this entire conversation has been Claude for architecture/spec and Antigravity for implementation with manual plan review at each step, this section is a genuine opportunity, not just a formality: it's a place to demonstrate the same reliability discipline the product itself claims to have, applied reflexively to your own process. Draft: *"Used Claude for architecture design, deriving the reliability rules directly from source-document language, and specifying the evaluation suite before implementation. Used Google Antigravity for implementation against that specification, with manual review of every Implementation Plan before execution and correction of drift back to the locked spec (e.g., reverting attempts at a generic query interface or hardcoded account branches). Numeric business logic was unit-tested independent of the LLM specifically to prevent hallucinated values reaching users."* Honest, specific, and it closes the loop on the same argument the rest of the submission is making.

---

## 1. Paste this at the start of your very first Antigravity task

```
Build against build_spec.md as ground truth. Hard constraints, no exceptions:
- No LangGraph or any agent framework — explicit tool-calling loop only.
- No generic query_data(query_type, params) interface — named tools only 
  (get_order, get_cancellation_terms, get_credit_terms, etc.)
- confirm_action is NEVER an LLM-callable tool. It's a plain backend endpoint the 
  frontend calls after a human clicks Confirm. The model must never see it in its tool list.
- Session scope uses account IDs (ACCT-001/ACCT-002), never customer names, and is 
  server-injected — never accept an account_id argument from the model.
- Account-specific overrides (cancellation waiver, credit terms, response times) live in a 
  config dict (ACCOUNT_TERMS), never as if/elif branches on account_id.
- If any part of this spec seems wrong or infeasible, stop and tell me — do not silently 
  change or skip it.
- Never edit a test's expected value to make it pass. If a test fails, fix the code or 
  flag that the spec's expectation is wrong.

```

Also drop the same constraints into a project Skill (`.agents/skills/calquity-spec/SKILL.md`) so they persist across sessions without re-pasting — Antigravity reads Skills automatically on every task.

---

## 2. Review discipline per task

- Check Artifact Review Policy is NOT "Always Proceed" — you want the pause before code gets written, especially for the first few tasks and anything touching auth or the action/confirmation boundary.
- Read every Implementation Plan for the five red flags before clicking Proceed: LangGraph, generic query interface, confirm\_action as an LLM tool, customer names instead of account IDs, hardcoded account branches.
- Use inline comments on the plan artifact to correct drift — faster and more precise than a fresh prompt.
- For the eval suite's integration-layer tests, explicitly ask for browser-driven Walkthrough verification against the exact expected outputs in build\_spec.md §6, not a general "looks good."
- Don't mark a task done without an artifact (diff + walkthrough) backing the claim.
- One task per hour-by-hour block from build\_spec.md §7 — not "build the backend" as one request. Smaller plans are reviewable in two minutes; sprawling ones aren't.

---

## 3. Blocking prerequisites — resolve before Hour 0, not during it

**LLM API access — checked against current published limits, not assumed:**

Gemini free tier (current as of this year): Gemini 2.5 Pro is roughly 5 RPM / 50–100 requests per day — too restrictive to build against; you'll hit the daily cap during normal development, before the reviewer ever sees it. **Use Gemini 2.5 Flash as primary** (roughly 10 RPM, several hundred to \~1,500 RPD depending on current quota) — enough for iterative development and for a reviewer testing the live app afterward, as long as you're not running the full eval suite in a tight parallel burst. Flash-Lite has meaningfully higher throughput as a fallback if Flash's RPM is the bottleneck, at some quality cost. Free tier has no SLA — Google can deprioritize free-tier requests during peak load, and prompts/responses may be used to improve their models (irrelevant here since the data pack is synthetic, but worth knowing).

**Grok — verify what you actually have before assuming it's a usable fallback.** There are two completely different things called "free Grok access": (1) the consumer chat app (grok.com / X), which is not a programmatic API at all and can't be called from a backend, and (2) the xAI developer API (console.x.ai), which does have a genuine $0-spend tier with its own rate limits and is OpenAI-SDK-compatible. If what you have is (1), it's not usable here — check console.x.ai specifically for an API key before building any fallback logic around it. If it's genuinely (2), it's a real second provider, not just a second key to the same pool (rate limits are per-provider, so Gemini + Grok is real diversification in a way that two Gemini keys would not be).

**If Grok API access is confirmed real:** a minimal fallback is cheap and worth building — try Gemini, catch the 429, fall back to Grok, both wrapped in basic exponential backoff. This is maybe 30–60 minutes of work, and it's not scope creep — it's the same "reliability is a system property" thesis applied to your own infrastructure instead of just the business logic. Worth one line in the architecture note's trade-offs section either way, since "single upstream LLM provider, no fallback" is a real and honest limitation if you don't build it.

**Exact submission requirements**: covered in §0 above, now confirmed rather than inferred.

---

## 4. Deployment risk that's easy to miss

Free-tier hosts (Railway/Render free plans) spin down after inactivity — a reviewer clicking your link cold can see a 20–30 second hang before the app responds, which reads as "broken" on a first impression, not "slow." If you're on a free tier, either note the cold-start behavior explicitly in your README ("first load may take \~20s, the app is sleeping not broken") or ping the deployed URL yourself shortly before you expect it to be reviewed.

---

## 5. Submission hygiene

- Commit incrementally with real messages tied to the plan's stages, not one final commit — a reviewer glancing at commit history is reading it as a process signal.
- `.env` gitignored, no API keys committed, a `.env.example` showing what's needed.
- README has literal run instructions: env vars required, how to rebuild the vector store, how to seed SQLite from the Excel, how to run the eval suite. Assume the reviewer might run it locally in addition to clicking the hosted link.

---

## 6. Minimum-viable floor, if Day 1 slips

If you're not at the Day 1 exit criterion (reasoning\_02 passing) by hour 9, the floor to protect — cut everything else first:

1. One working context (internal, since it exercises full capability) with the three real tools + the two calculation functions, correctly handling the Northstar and LumenWorks cancellation questions.
2. Access control enforced and tested (security\_01/02), even without a polished UI.
3. Confirmation gate on the one action tool, working end to end.
4. A README that honestly states what's built and what's deferred — an honest partial submission with real product judgment beats a broken attempt at the full scope.

Proactive detection, the third calculation function, and UI polish are the first, second, and third things to drop — in that order.

---

## 7. After submission, if it leads to an interview

Antigravity wrote a lot of this code — you still need to be able to walk through any file and explain any decision without hesitating, since that's very likely to come up. Budget 20–30 minutes before submission to skim every generated file once, not just trust the Walkthrough summaries. If a decision in the code doesn't match something you can explain, that's worth fixing or at least being ready to discuss honestly, not glossing over.