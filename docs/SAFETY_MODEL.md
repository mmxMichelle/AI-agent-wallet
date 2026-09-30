# Safety model

This is a portfolio prototype, not production financial software. Local AI
proposes, deterministic software enforces, humans approve when required, and
Daml remains authoritative. No external LLM is used.

## Financial and language boundaries

The parser requires an explicit recipient, positive Decimal amount and CC
currency. It supports recipient-first Pay/Send and amount-first Send/Transfer
forms with optional `for PURPOSE`. It never infers identities, percentages,
approximate amounts or missing fields. Invalid/ambiguous text yields
CLARIFICATION_REQUIRED and BLOCK_PRE_LEDGER before wallet-context access.
Purpose instructions are inert text; blocked literal category terms are retained.
Money and policy comparisons use Decimal, not model feature floats.

The read-only allowlist remains balance, transaction history, recipient history,
policy retrieval and risk calculation. Arguments must be exactly `{}`; intent,
context and policy are bound by trusted application code. There are no execution,
shell, filesystem-path, arbitrary HTTP, approve or settle tools. A malformed or
out-of-order planner action fails closed. Local component exceptions and bounded
step exhaustion also block; neither can trigger fallback execution.

## Monotonic guardrail

```text
PROCEED_TO_DAML < REQUIRE_HUMAN_CONFIRMATION < BLOCK_PRE_LEDGER
final_action = max(planner_action, deterministic_action)
```

The guardrail implementation and financial thresholds are unchanged. Insufficient
balance, blocked category, hard maximum and hard balance-fraction violations
block. Daily-budget and review-threshold violations, new recipients (according
to policy), high anomaly score and insufficient proposal confidence require
review unless already blocked. The learned score can only raise the prior
weighted heuristic signal, never lower it. Low anomaly cannot excuse overspending.

The local kNN model is a behavioural anomaly detector, not a fraud probability
estimator. It learns scaled distances from synthetic reference behaviour. It has
no keys, signer authority or tool access. Anomaly score must be finite and in
[0,1]; errors block. Hard policy can short-circuit unnecessary ML work.

## Human and execution boundaries

Human YES can permit review to reach the controller; NO produces
REJECTED_BY_HUMAN without submission. Invalid input/EOF leaves WAITING_FOR_HUMAN.
Hard blocks do not prompt and cannot be overridden. Noninteractive assessment
never submits. Event-loop low-risk events can reach explicitly configured mock
execution autonomously.

The existing controller refreshes context and deterministic preflight before any
handoff, preserves the original restriction, and consumes successful/declined
assessments to prevent local replay. It consumes before a potentially ambiguous
execution result and never automatically retries. The coordinator records a
sanitized failure requiring reconciliation if the adapter raises. The model and
planner never invoke the adapter directly.

Mock execution means WOULD_SUBMIT with detail "Would submit to existing Daml
Mandate; no Canton Coin moved". Optional memory records a demo reservation for
subsequent events, not settlement or recipient trust. Legacy execution remains
opt-in, lazy, and absent from CLI. Existing Daml signatories/controllers,
Mandate restrictions, human owner approval and Canton settlement are unchanged.

## Audit and privacy

Transitions record from/to state, action and public reason; observations record
state, selected action and a bounded public summary. Structured audit includes
features, anomaly score, risk signals, policy references, final decision, human
response and outcome. No raw history, credentials or private reasoning is logged.
Raw exceptions are not propagated to audit records. See [privacy](PRIVACY_MODEL.md).

## Remaining limitations

- The host process, local policy, input context, model and planner implementations
  are trusted code, not an adversarial process-isolation boundary.
- The grammar is intentionally narrow. Recipient names are not authenticated
  identities; blocked-category matching is literal, not semantic understanding.
- Demo thresholds, synthetic kNN training and calibration are not validated for
  production fraud detection. Novel legitimate transactions may be escalated.
- Elapsed-time features require explicit valid timestamps and are missing in
  default assessments. No live history synchronization or online retraining.
- JSON memory is a single-process demo store. No distributed locking, durable
  event deduplication, multi-process reservations, or crash-proof reconciliation.
- Repeated mock reservations do not create real holdings or settled history.
  Unanswered reviews are recorded but have no cross-process resume API.
- Human input is a terminal response, not authenticated consent. Audits are not
  tamper-evident or encrypted. Model inference adds no ledger authority.
- Execution preflight refreshes deterministic policy/context; it does not rerun
  ML. Prior ML restriction remains binding. Production needs explicit freshness.
- No LocalNet, DevNet, live Canton, owner-signature or real-money integration was
  run during this redesign. Existing non-atomic settlement semantics are intact.
