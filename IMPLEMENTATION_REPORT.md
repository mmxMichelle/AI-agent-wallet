# Implementation report

Completed locally on 2026-09-30 on `feature/governed-ai-agent`.
No clone, push, pull request, merge, history rewrite, or commit was performed.
The backup branch `backup/pre-ai-agent-baseline` was retained.

## Baseline and scope

The writable repository started clean at `5a99eea`. Before editing:

| Command | Result |
|---|---|
| `python3 -m unittest python/test_mandate_client.py -v` | 13 passed |
| `python3 -m unittest python/test_demo_ui.py -v` | 4 passed |

Both local trees were inspected. The read-only `hackathon-toolkit` already had
a modified `daml-starter/daml/Mandate.daml` and untracked `get-daml.sh`; those
pre-existing changes were reported and left untouched. No files were created,
formatted, moved, or edited in that tree. All new assets are inside AI-agent-wallet.

Legacy entry points are `python/mandate_client.py` command builders and
`submit_command`, `DemoState.request_payment` / `approve_payment` / `reject_payment`,
and `c8lab.py` CLI/helpers. Settlement is `DemoState._settle` ->
`mandate_client.settle_payment` -> `c8lab.transfer`, with offer acceptance through
`c8lab.accept_transfer`. Daml Mandate and PendingPayment choices control the
existing authorization boundary; settlement is separate from the Daml record.

## Implemented

- Strict immutable domain objects and Decimal monetary validation.
- Grounded natural-language parsing with explicit clarification failures.
- Provider Protocol, deterministic scripted mock, optional HTTPS-compatible
  inference transport with sanitized errors and no vendor dependency.
- Local JSON policy/history, deterministic token retrieval, recipient statistics,
  bounded anomaly signals, and full-policy deterministic preflight.
- Five read-only allowlisted tools and a bounded model/tool loop.
- Monotonic safety escalation, including guardrails when the model skips tools.
- Separate execution controller with fresh preflight, explicit yes/no, local
  replay protection, mock recording, and disabled-by-default lazy legacy adapters.
- Parse, assess, demo, and eval CLI commands; offline is the default.
- Structured stdout audit records without credentials or private reasoning.
- Thirty golden scenarios, five calculated metrics, and 58 offline tests.
- Architecture, safety, evaluation, and additive README documentation.

## Files added

```text
.env.example
IMPLEMENTATION_REPORT.md
ai_agent/__init__.py
ai_agent/cli.py
ai_agent/config.py
ai_agent/evaluation.py
ai_agent/guardrail.py
ai_agent/ledger.py
ai_agent/legacy_adapter.py
ai_agent/logging_utils.py
ai_agent/memory.py
ai_agent/models.py
ai_agent/orchestrator.py
ai_agent/parser.py
ai_agent/policy.py
ai_agent/providers.py
ai_agent/retrieval.py
ai_agent/risk.py
ai_agent/tools.py
config/wallet_policy.json
data/demo_history.json
eval/scenarios.json
docs/AI_AGENT_ARCHITECTURE.md
docs/SAFETY_MODEL.md
docs/EVALUATION.md
tests/test_cli_audit.py
tests/test_evaluation.py
tests/test_execution_adapter.py
tests/test_guardrail.py
tests/test_legacy_boundary.py
tests/test_models.py
tests/test_orchestrator.py
tests/test_parser.py
tests/test_policy.py
tests/test_providers.py
tests/test_retrieval.py
tests/test_risk.py
tests/test_tools.py
```

Only existing file modified: `README.md`, with an entry link and additive AI
Agent Extension section. The original explanation remains intact.

Deliberately unchanged: `c8lab.py`; all existing files under `python/`, including
`mandate_client.py`, `demo_ui.py`, `live_monitor.py`, `monitor_state.py`, existing
tests and requirements; all of `daml-starter/`, including Mandate, Iou, Test and
`daml.yaml`; existing setup/API/troubleshooting documents and demo video.

## Architecture decisions

Use explicit standard-library code so the orchestration and authority boundary
can be explained and audited. Use JSON snapshots rather than adding a database;
mock submissions intentionally do not alter balances or invent settled history.
Use lexical policy retrieval rather than hosted embeddings. Compute risk from
trusted snapshots rather than model assertions. Always run full deterministic
policy independently of retrieval and tool selection. Preserve the more
restrictive of model and guardrail actions.

Keep the existing UI and settlement flow frozen. The optional legacy execution
adapter wraps Mandate command submission only; existing owner approval and
settlement continue outside the new agent. Remote inference changes no execution
permissions. No live-execution CLI was added because live context freshness,
authenticated approvals, and reconciliation need separate integration work.

## Verification

| Check | Actual result |
|---|---|
| New suite: `python3 -m unittest discover -s tests -v` | 58 passed |
| Post-change mandate regression | 13 passed |
| Post-change demo UI regression | 4 passed |
| Additional offline UI workflow test | create, small payment, approve, reject passed with HTTP forbidden |
| Offline boundary subprocess | assessment, mock controller, all scenarios pass with sockets and legacy imports forbidden |
| Frozen legacy diff against backup | no changes in `c8lab.py`, `python/`, `daml-starter/` |
| CLI parse, assess, demo, eval | executed locally; EOF leaves review awaiting approval |
| Human yes/no paths | exercised through CLI/controller tests |

The first new test run found a defect in the network-blocking test fixture: it
replaced the socket class with a function, preventing Python's SSL module from
being imported. The fixture now preserves the class shape while rejecting socket
creation. No legacy implementation was changed to fix this test.

Golden results from actual execution: 30/30 action matches; unsafe proceed
0/26 = 0%; human review 8/30 = 26.67%; false escalation 0/4 = 0%; policy compliance
30/30 = 100%. Evaluation tests also verify detection of deliberately mismatched
expectations. See `docs/EVALUATION.md` for exact definitions and limitations.

## Reproduce

```bash
cd /Users/mamingxuan/Cantor8/AI-agent-wallet
python3 -m ai_agent.cli parse "Pay Alice 0.1 CC for coffee"
python3 -m ai_agent.cli assess "Pay Alice 0.05 CC for coffee"
python3 -m ai_agent.cli assess "Pay Charlie 0.6 CC for dinner"
python3 -m ai_agent.cli assess "Pay UnknownXYZ 0.9 CC for dinner"
python3 -m ai_agent.cli demo
python3 -m ai_agent.cli eval
python3 -m unittest discover -s tests -v
python3 -m unittest python/test_mandate_client.py -v
python3 -m unittest python/test_demo_ui.py -v
git diff --check
```

The original UI can still be launched independently with
`python3 python/demo_ui.py --offline-demo`.

## Limitations and untested functionality

The offline AI demo does not move real Canton Coin. This is a research / portfolio
/ hackathon-derived prototype, not production-ready financial software.
Natural language currently uses a limited explicit Pay/Send grammar; percentages
require clarification. The mock is not a learned model. Context is static demo
data, category checks are literal, confidence is uncalibrated, and anomaly weights
are illustrative. Audit records are not tamper-evident and replay prevention is
not durable across processes. The application/operator remains a trusted boundary.

Only optional remote inference requires an external LLM, endpoint, and credentials;
its transport was tested with fakes, never with a real endpoint. Optional live
holdings/Mandate submission requires Canton configuration, trusted identities,
contract state, and suitable permissions. Those adapters were inspected and
tested with fakes only. No Canton runtime, LocalNet, DevNet, live owner approval,
or real settlement was tested. No new DevNet verification claim is made.

## Recommended next steps

Review and commit the extension with:
`feat: add offline governed AI payment agent with deterministic guardrails`

Demonstrate the mock CLI and explain its authority boundaries. Expand independent
adversarial scenarios and language coverage while retaining grounding. In a
separately provisioned environment, integrate fresh ledger history, authenticated
human approval, durable idempotency/reconciliation, and trusted contract/party
resolution before attempting the optional Mandate adapter. Consider UI integration
only through an isolated adapter after those boundaries are reviewed.
