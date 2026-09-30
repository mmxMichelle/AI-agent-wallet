# GuardRail Wallet
## Privacy-Preserving Autonomous AI Payment Agent

GuardRail Wallet is a local-first autonomous payment agent combining deterministic payment-intent parsing, observe-plan-act orchestration, state-machine planning, local transaction-context analysis, local unsupervised anomaly detection, deterministic financial guardrails, human-in-the-loop review, and an existing Daml/Canton execution boundary.

**No external LLM is used. No wallet data is sent to an external AI provider.** No OpenAI API is used. The current AI demo runs with offline mock execution.

> Observe locally. Learn locally. Plan locally. Enforce deterministically. Keep payment authority outside the AI.

## Highlights

- Fully local autonomous agent: explicit state machine, planner and observe-plan-act workflow.
- 14-feature behavioural transaction analysis with a dependency-free `LocalKNNAnomalyModel`.
- Deterministic monotonic financial guardrails and human-in-the-loop escalation.
- Network-independent AI layer: no external LLM, API key or model server.
- Offline execution adapter around the existing Daml/Canton boundary.
- 33-scenario golden evaluation: **0 unsafe-proceed cases in the current offline suite**.

## Core Payment Flow Demo

The demo below shows the underlying GuardRail Wallet payment workflow, including policy-controlled payments, human approval and the Daml/Canton execution layer.

https://github.com/user-attachments/assets/6bea3491-8094-4818-9d60-55a0e4ee22c9

🎥 [Watch the GuardRail Wallet demo](demo/GuardRail-Wallet-How-It-Works.mp4)

The current version keeps this execution boundary and adds a fully local autonomous AI layer upstream for transaction-context analysis, behavioural anomaly detection, planning and risk assessment. The video primarily demonstrates the payment/execution workflow and predates the latest agent internals; it does not directly visualise the new KNN anomaly model, state machine or planner.

The autonomous redesign was validated offline and does **not** claim current live Canton Coin validation.

## Architecture

```text
Payment Event
      v
Deterministic Intent Parser
      v
Autonomous State Machine
      +--> Balance
      +--> Recipient History
      +--> Transaction History
      +--> Local Policy
      v
Feature Engineering
      v
Local ML Anomaly Model
      v
Risk Engine
      v
Autonomous Planner
      v
Deterministic Guardrail
     /          |           \
 BLOCK        HUMAN        PROCEED
                |              |
                v              v
          Human Review    Daml Boundary
                               v
                         Canton Layer
```

ML provides a signal; the planner chooses bounded next actions; deterministic guardrails retain authority. Approved reviews return through guarded execution. The diagram shows the conceptual execution boundary: the current AI CLI uses a mock adapter, without contacting Canton. Payment authority stays outside the AI.

## What Makes It Autonomous?

**Agent != LLM.** An explicit planner and state machine drive the loop:

1. Receive a payment event and inspect current state.
2. Determine missing information and select allowed local actions.
3. Gather observations, build features and run local anomaly inference.
4. Assess risk and policy, then choose the next action.
5. Execute through the separate controller, block, or request human review.
6. Record the outcome and continue to the next event.

Planning adapts to observations: invalid intent stops before wallet-context access, cached observations are reused, and hard blocks skip unnecessary history and ML work. A step budget prevents unbounded execution.

## Why Local AI Instead of an LLM?

This project intentionally prioritises confidentiality, deterministic behaviour, auditability, reproducibility, fail-closed semantics and explicit financial authority boundaries. Ambiguous financial language is deliberately clarified or rejected instead of being guessed by a probabilistic language model. This is a scoped engineering choice for payment control.

## Local Machine Learning

`LocalKNNAnomalyModel` is dependency-free and deterministic, with local fitting and inference. It fits **128 synthetic reference vectors using fixed seed 2048**, separately from the golden evaluation scenarios. Robust scaling and nearest-neighbour distances produce a normalised **behavioural anomaly score in [0, 1]**; the score is not a fraud probability. The 14 transaction/wallet-context features are:

- Amount; amount-to-balance ratio.
- Recipient transaction count, frequency and average amount; amount relative to that average.
- Overall average amount; amount relative to that average.
- Daily spend; proposed daily spend divided by daily budget.
- New-recipient and trusted-recipient flags.
- Elapsed time since the last recipient payment; missing-time indicator.

Financial policy uses `Decimal`; numerical ML features use floats. Synthetic references and development-time calibration limit generalisation; the golden suite is regression coverage, not a held-out ML benchmark.

## Quick Start

Run from the repository root with Python 3.10+; the standard library is sufficient. **No API key, LLM server or external AI provider is required.** Canton is not required for these offline commands.

```bash
# Single assessment (decision only)
python3 -m ai_agent.cli assess \
  "Pay Alice 0.05 CC for coffee"
# Interactive review and guarded mock execution
python3 -m ai_agent.cli assess \
  "Pay Charlie 0.6 CC for dinner" --interactive
# Autonomous demo / interactive event source
python3 -m ai_agent.cli run-agent --source demo
python3 -m ai_agent.cli run-agent --source stdin
# Model information / offline evaluation
python3 -m ai_agent.cli model-info
python3 -m ai_agent.cli eval
```

## Example Agent Behaviour

| Risk (demo context) | Request | Expected behaviour |
|---|---|---|
| Low | `Pay Alice 0.05 CC for coffee` | `PROCEED_TO_DAML`; guarded mock execution returns `WOULD_SUBMIT`. |
| Medium | `Pay Charlie 0.6 CC for dinner` | `REQUIRE_HUMAN_CONFIRMATION`: new recipient, amount above review threshold and/or high anomaly score. |
| High | `Pay UnknownXYZ 0.9 CC for dinner` | `BLOCK_PRE_LEDGER`; hard deterministic blocks cannot be overridden. |

For review, human **yes** may proceed to the mock Daml boundary; **no** yields `REJECTED_BY_HUMAN`. Blank, unrecognised or missing approval leaves the transaction waiting. `assess` alone does not execute; use `--interactive` or the agent demo for mock execution. **No real Canton Coin is moved in the offline demo.**

## State Machine / Planner

The planner selects the next missing observation or bounded action. The state machine validates and records lifecycle transitions; see [AI Agent Architecture](docs/AI_AGENT_ARCHITECTURE.md) for full details:

```text
RECEIVED, VALIDATING, GATHERING_CONTEXT, BUILDING_FEATURES,
ASSESSING_ANOMALY, ASSESSING_RISK, PLANNING, WAITING_FOR_HUMAN,
READY_FOR_EXECUTION, EXECUTING, BLOCKED, COMPLETED, FAILED
```

## Privacy Model

In AI mode, the raw payment request, recipient identity, transaction history, balance, feature vectors, anomaly inference, policy, risk score, planner state and audit data stay local.

**The local AI layer was validated with socket networking and DNS disabled.** Canton networking, if separately configured, belongs to the existing execution boundary and is not part of external AI inference. The host process and local storage remain trusted; these tests are not an OS sandbox. See [Privacy Model](docs/PRIVACY_MODEL.md).

## Safety Model

`PROCEED_TO_DAML < REQUIRE_HUMAN_CONFIRMATION < BLOCK_PRE_LEDGER`

Safety is monotonic: a downstream safety layer may only make a decision more restrictive. ML cannot override invalid intent, insufficient balance, blocked categories, hard amount limits, maximum balance fractions or other deterministic policy rules. **Human approval cannot override a hard block.** The separate execution controller refreshes preflight before handoff. See [Safety Model](docs/SAFETY_MODEL.md).

## Evaluation

Current **fixture-based offline evaluation results**, recorded in the [implementation report](IMPLEMENTATION_REPORT.md) and [evaluation documentation](docs/EVALUATION.md):

| Check / metric | Result |
|---|---:|
| AI tests | 113 passed |
| Legacy mandate / demo UI regression tests | 13 / 4 passed |
| Golden scenarios | 33 / 33 passed |
| Action accuracy on the fixture suite | 100% |
| `unsafe_proceed_rate` | 0 (0 unsafe-proceed cases) |
| `human_review_rate` | 21.21% |
| `false_escalation_rate` | 0% |
| `policy_compliance_rate` | 100% |

These results describe this small offline fixture suite, not general AI accuracy, fraud detection accuracy or production guarantees. Evaluation performs no ledger writes or settlement.

## Repository Structure

```text
ai_agent/
  agent_loop.py      # Observe-plan-act orchestration
  anomaly.py         # Local KNN model
  event_source.py    # Demo, stdin and JSONL events
  features.py        # 14 context features
  planner.py         # Bounded next actions
  state_machine.py   # Explicit lifecycle
  parser.py          # Deterministic payment grammar
  risk.py            # Risk signals
  guardrail.py       # Monotonic policy enforcement
  memory.py          # Local demo state and outcomes
  tools.py           # Read-only local observations
  ledger.py          # Separate execution controller
  cli.py             # Offline command-line entry point
config/              # Local policy
data/                # Demo history
eval/                # Golden scenarios
tests/               # AI regression suite
docs/                # Architecture, privacy, safety, evaluation
python/              # Existing payment clients and monitor
daml-starter/        # Existing Daml contracts
c8lab.py             # Canton toolkit
IMPLEMENTATION_REPORT.md
```

## Daml/Canton Execution Boundary

The autonomous agent is built around the existing Daml/Canton payment boundary. The original contracts and settlement semantics were intentionally kept separate from the local AI redesign. Daml mandates control spending and approval; the existing Python clients and Canton toolkit support the separate execution workflow.

**The current autonomous-agent validation uses offline mock execution and was not revalidated against DevNet or real Canton Coin as part of this redesign.** `WOULD_SUBMIT` records a mock handoff, not settlement. Historical execution setup remains documented below.

## Limitations

- Synthetic anomaly reference data; no production fraud labels.
- Narrow deterministic payment grammar.
- Single-process memory, unauthenticated terminal approvals and no cross-process review resumption.
- No current live Canton or real-money validation for the autonomous redesign.

**This is a portfolio prototype, not production financial software.**

## Documentation

- Local agent: [Architecture](docs/AI_AGENT_ARCHITECTURE.md), [Privacy](docs/PRIVACY_MODEL.md), [Safety](docs/SAFETY_MODEL.md), [Evaluation](docs/EVALUATION.md), [Implementation Report](IMPLEMENTATION_REPORT.md).
- Existing execution layer: [Setup](SETUP.md), [API](API.md), [Troubleshooting](TROUBLESHOOTING.md), [Original Challenges](CHALLENGES.md).

## Project Positioning

How can an AI payment agent gain useful autonomy without giving probabilistic AI unrestricted financial authority or exposing wallet context to external AI services?

- **Local ML** → behavioural anomaly signal.
- **Autonomous agent** → observes state and plans bounded actions.
- **Deterministic guardrails** → enforce financial rules.
- **Human** → resolves review-required transactions.
- **Daml / Canton** → remains the payment-authority boundary.

**The AI is local. The safety rules are deterministic. The payment authority stays outside the AI.**
