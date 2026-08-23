# Product Note

## 1. Additional Client Problem
We chose to address **Problem 2: Trust & Reliability** directly within the core architecture of the application. In the logistics space, hallucinations surrounding financial calculations, service level agreements, or cancellation fees can lead to severe liability and customer distrust. We solved this by creating a hybrid reasoning model where the LLM is isolated from mathematical computations and policy resolution. The LLM parses natural language, but deterministic Python code calculates credit amounts and validates SLA breaches based on an immutable hierarchy of contracts and SOPs.

## 2. Future Work (What Else We'd Build)
Given additional time, we would build out **Problem 1: Proactive Detection**. We would introduce scheduled background jobs that continuously scan the database for late pickups (e.g., webhook delays) or SLA breaches, generating `PendingAction` alerts for Ops teams to review and confirm *before* the customer even files a ticket.

## 3. What Was Intentionally Left Out
- **Vector Database (Pinecone/Weaviate):** We omitted heavy external vector databases in favor of local SQLite FTS5 for simplicity, ensuring zero-configuration deployment and easier transactional guarantees between structured constraints and semantic text.
- **Complex Agentic Loops (AutoGPT/LangChain React):** We explicitly rejected recursive agent loops that can fall into infinite iterations or unpredictable tool use, opting for a strict pipeline (Extract -> Deterministic Execute -> Format).
- **Grok Fallback:** To keep the initial architecture minimal and avoid API key complexity for the judges, we only implemented Gemini 2.5 Flash as the generative backend.

## 4. Success Metric
To judge whether the product is useful, the primary metric we would track is **First-Touch Resolution Rate (FTRR) vs. Escalation Rate**, specifically for computationally intensive tickets like Service Credits and Cancellations. If the system correctly calculates and prepares the action for human confirmation (or auto-execution for customers) without a human agent needing to open the SOPs or Calculator, the product is providing material leverage.
