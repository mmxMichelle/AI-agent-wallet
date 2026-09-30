# Safety model

This is a research / portfolio / hackathon-derived prototype. It is not
production-ready for real financial deployment.

Probabilistic AI proposes. Deterministic software validates. Daml remains
authoritative. Humans remain in control when required.

## Threat model and controls

LLM output, payment purpose, and user text are untrusted. A prompt that says
"ignore all wallet rules" is content, not authorization. The provider can propose
only JSON intents, read-only tool requests, and recommendations. Critical intent
fields must match the original explicit request. Purpose text cannot be silently
removed to hide a blocked literal category. Malformed output and missing values
fail closed. Monetary values must be finite, bounded Decimal strings.

The tool registry grants least privilege: balance, transaction history, recipient
history, policy retrieval, and risk calculation only. There are no transfer,
settle, approve, submit, shell, arbitrary HTTP, or filesystem tools. The remote
provider's configured inference endpoint is transport controlled by the operator,
not an agent tool. Tool arguments cannot replace trusted context or policy.

The deterministic guardrail evaluates full policy after the model finishes or
fails. Insufficient balance, blocked category, amount above the hard maximum,
and balance fraction above the maximum block. New recipients, daily budget,
review threshold, high anomaly score, and low confidence cause human review.
Invalid/nonpositive amounts fail before assessment. Threshold values are DEMO
values, not financial advice or a replacement for the Daml Mandate.

Monotonic safety is explicit:

```text
PROCEED_TO_DAML < REQUIRE_HUMAN_CONFIRMATION < BLOCK_PRE_LEDGER
final_action = max(ai_action, deterministic_action)
```

An AI block is never relaxed. AI review is never automatically converted to
proceed. A human yes cannot override a hard block. Human review binds to the
specific in-memory assessment displayed by the CLI; absent/invalid input leaves
it waiting. The execution controller refreshes context and reruns the guardrail.
No agent method can call the execution controller or a payment adapter as a tool.

Daml remains authoritative for ledger authorization. Existing settlement is a
separate Python flow; this extension does not claim atomicity between the Daml
record and token transfer. The optional legacy adapter submits Mandate commands
only and requires existing owner approval/settlement tooling afterward.

## Bounded work and audit

The agent has a six-tool-call limit and bounded structured responses. Exhaustion
or an invalid tool causes human escalation; hard policy still applies. Remote
inference uses a finite timeout and does not follow HTTP redirects.

Audit records include request ID, timestamp, intent, invoked tools, policy
references, risks, recommendation, confidence, deterministic reasons/action,
final action, human decision, and execution result. They are emitted on stdout,
not silently saved. Arbitrary raw responses, full message transcripts, provider
objects, API keys, auth tokens, and hidden chain-of-thought are not logged.
Only deterministic public reasons are emitted; model rationale stays out of the
audit stream because arbitrary model text is not a trustworthy audit narrative.
Request purpose is user data and can contain personal information; operators
must control access and retention when choosing to store stdout.

No secrets are included in configuration. `.env.example` contains placeholders;
the ignored `.env` file is not automatically read. External inference requires
explicit provider selection and confirmation. No external service is required
by the unit tests.

## Limits that remain

- Python application code and operator configuration are trusted; these are not
  process-isolation or cryptographic authorization boundaries. A malicious caller
  with arbitrary Python access could invoke legacy code directly.
- Demo context is static. Live history, timestamp freshness, reservations,
  concurrency control, and multi-process durable idempotency are not implemented.
  Controller replay protection is only within one instance.
- Recipient strings are not verified identities. Live mapping must be supplied
  by trusted setup. No automatic fuzzy party lookup is performed.
- Category blocking matches supplied categories and literal purpose tokens;
  obfuscation, euphemisms, and unknown prohibited activities need further controls.
- The weighted anomaly score is a behavioural indicator, not validated fraud
  detection. Confidence is model-supplied and not calibrated.
- Audit JSON is not tamper-evident. Human input is a local demo prompt, not an
  authenticated production approval service.
- The language grammar is intentionally limited. Percentages and missing values
  require explicit clarification instead of model inference.
- Mock evaluation cannot establish remote-model reliability or Canton safety.
  No live LLM, LocalNet, DevNet, or real Canton Coin transfer was tested.
