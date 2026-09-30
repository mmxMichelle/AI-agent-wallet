# Local autonomous agent architecture

The AI layer performs no network I/O and uses no LLM. The original `c8lab.py`,
`python/` payment implementation and `daml-starter/` contracts are frozen.

Agent != LLM. Here the agent combines local perception, immutable context,
transaction memory, allowlisted tools, unsupervised learning, planning, explicit
state, guarded actions, and outcome feedback. It is not an unbounded daemon.

## Components

| Module | Responsibility |
|---|---|
| `parser.py` | Explicit grammar -> validated Decimal PaymentIntent; ambiguity blocks |
| `models.py` | Immutable financial schemas, strict JSON and Decimal validation |
| `event_source.py` | Finite demo, stdin, and local JSONL events |
| `state_machine.py` | Valid lifecycle edges and auditable transition history |
| `planner.py` | Missing-observation selection and conservative local proposal |
| `agent_loop.py` | Bounded observe-plan-act loop and separate outcome coordinator |
| `orchestrator.py` | Compatibility import for the local agent API |
| `tools.py` | Snapshot-bound balance, recipient/history, policy and risk tools |
| `memory.py` | Trusted local context, optional JSON audit store, demo reservations |
| `features.py` | Fourteen ordered, finite numerical features |
| `anomaly.py` | Fitted local robust-scaled kNN anomaly detector |
| `risk.py` | Decimal policy signals plus monotonic learned anomaly contribution |
| `guardrail.py` | Unchanged hard rules, review rules, monotonic action combination |
| `ledger.py` | Explicit controller; fresh deterministic preflight and replay protection |
| `legacy_adapter.py` | Existing disabled-by-default lazy legacy boundary wrappers |
| `logging_utils.py` | Structured public audit fields, no raw history or credentials |
| `evaluation.py` | Actual local assessment runs and computed fixture metrics |

## Observe-plan-act

Each event starts with a fresh session. The planner sees observations already
available and returns a typed Step. The loop validates that step, performs its
allowed action, records a compact public observation, and asks the planner again.
The executor rejects out-of-order steps and guardrail-bypassing proposals.

1. Validate intent before reading a context snapshot. Invalid input blocks.
2. Fetch balance and retrieve policy through bound local tools. Hard deterministic
   rules can shortcut directly to risk/guardrail without model or history tools.
3. Fetch missing recipient and transaction history. One snapshot is reused within
   an assessment; no duplicate observation request is accepted.
4. Build features, infer a local score, compute risk, and propose an action.
5. Apply the independent deterministic guardrail. Stop assessment in BLOCKED,
   WAITING_FOR_HUMAN, or READY_FOR_EXECUTION.
6. The event coordinator obtains any required human decision and calls the
   separate execution controller. The model and read-only tools cannot submit.
7. Record the outcome in local memory before receiving the next event.

`assess` performs steps 1–5 only unless `--interactive` is selected. `run-agent`
uses the finite event loop and mock execution. Default limits are 20 assessment
steps and 20 events (configurable within 1–100 and 1–1000). Exhaustion or local
component failure blocks without execution. Exceptions are sanitized rather than
recording arbitrary tool/model text. No private reasoning is generated or logged.

## States and planning actions

States: RECEIVED, VALIDATING, GATHERING_CONTEXT, BUILDING_FEATURES,
ASSESSING_ANOMALY, ASSESSING_RISK, PLANNING, WAITING_FOR_HUMAN,
READY_FOR_EXECUTION, EXECUTING, BLOCKED, COMPLETED, FAILED.

Actions: VALIDATE_INTENT, FETCH_BALANCE, LOAD_POLICY, FETCH_RECIPIENT_HISTORY,
FETCH_TRANSACTION_HISTORY, BUILD_FEATURES, RUN_ANOMALY_MODEL, ASSESS_RISK, PLAN,
REQUIRE_HUMAN, BLOCK, EXECUTE, COMPLETE. COMPLETE is an outcome-coordinator
transition; EXECUTE during assessment only marks readiness, never submits.

The state-machine edge table rejects illegal transitions. Any nonterminal state
may fail closed. COMPLETED cannot be reopened. Review can complete as rejection,
remain waiting, or move through READY_FOR_EXECUTION and EXECUTING after explicit
approval. A refreshed execution check can still block or require review.

## Learning and features

The dependency-free LocalKNNAnomalyModel fits 128 synthetic reference vectors
using fixed seed 2048. Synthetic identities, amounts and contexts are generated
independently of evaluation inputs. These are demo normal-behaviour examples,
not real financial history or fraud labels. No network, cloud, downloads, or
pickled code is involved. Scikit-learn was unavailable and is not a dependency.

Feature order is defined by TransactionFeatures fields:
amount, amount_to_balance_ratio, recipient_transaction_count,
recipient_frequency, recipient_average_amount, amount_vs_recipient_average,
overall_average_amount, amount_vs_overall_average, daily_spend, daily_spend_ratio,
new_recipient, trusted_recipient, time_since_last_recipient_payment,
recipient_time_missing. Budget ratio includes proposed spend. Missing averages
map to zero alongside explicit new-recipient status; zero balance maps to ratio
one and still triggers deterministic insufficient-balance checks. Optional
elapsed time requires explicit timezone-aware observation time; assessment uses
the missing indicator by default rather than wall-clock-dependent model inputs.

Training learns each feature's median and interquartile scale, with a scale floor
for constant features. Inference averages the three nearest normalized Euclidean
distances. The normalization uses median leave-one-out training distance:
`score = distance / (distance + 8 * reference_distance)`. The factor eight is a
conservative demo calibration, not a statistically calibrated probability. The
model detects unusual behaviour; it neither proves fraud nor authorizes payment.

The original weighted anomaly heuristic remains as a conservative policy signal.
Risk uses the maximum of it and the learned score; model selection cannot lower
existing restrictions. Model exceptions/invalid scores block. Hard financial
rules are independent of anomaly scores and evaluated even on early-block paths.

## Memory and authority

Default context comes from clearly labelled local demo history. Optional JSON
memory records audit outcomes and mock reservations only. Accepted mock handoffs
reduce available demo balance and increase demo daily spend for future events.
They do not create settled history, recipient trust, or online training examples.
Blocked/rejected/waiting events reserve nothing. Memory is bounded to 1000 audit
records, atomically replaced with mode 0600, and tested with temporary paths.
Fixture files cannot be loaded as writable memory because their schema differs.
Use a fresh file to reset a demo; this is not ledger reconciliation.

The controller still refreshes context and reruns deterministic guardrails before
handoff; original assessment restrictions remain binding. Live execution requires
explicit trusted construction of the existing legacy adapter, a Mandate CID,
spender, recipient-party mapping, and complete trusted context. It has no live
CLI path. The existing Daml controllers and owner approval/settlement remain
separate. No new signer, secret, shell tool or unrestricted transfer was added.
