# Local autonomous agent implementation report

## Snapshot, scope and baseline

The working tree initially contained only the known provider experiment. It was
preserved in local commit `3de40d2` on
`backup/byom-before-local-autonomous-agent`. The redesign is on
`feature/local-autonomous-ai`. No branch was pushed, no history was rewritten,
and the redesign itself remains uncommitted for review.

Before editing, the baseline passed: 85 AI tests, 13 mandate tests, 4 demo UI
tests, and 30/30 golden scenarios with unsafe_proceed_rate = 0.

The frozen `c8lab.py`, all `python/` payment code including mandate_client and
demo_ui, and `daml-starter/` remain unchanged. Existing settlement and payment
command semantics were not modified. The read-only hackathon-toolkit dependency
was not modified, and nothing was cloned. Guardrail rules and thresholds are
unchanged. The existing execution controller changed only a docstring.

## Architectural decision

An earlier provider/BYOM/BYOK design was intentionally removed to keep financial
context inside the local trust boundary. Provider implementations, network
transports, endpoint/key/model settings, provider CLI flags and provider-specific
tests were deleted/replaced. History on the backup branch preserves that work;
there is no dormant external-inference path in the active architecture.

The product is now GuardRail Wallet — Privacy-Preserving Autonomous AI Payment
Agent. No external LLM is used. The implementation supports this accurate
portfolio description:

> Designed a local-first autonomous payment agent combining transaction-context
> analysis, unsupervised anomaly detection, state-machine planning,
> human-in-the-loop escalation and deterministic Daml-based execution controls.

> Kept financial data inside the local trust boundary rather than relying on
> hosted inference.

## Actual autonomy and modules

Events arrive from finite demo, stdin or local JSONL sources. A session records
observations and explicit lifecycle transitions. The planner chooses the next
missing observation, the loop invokes a bound read-only tool, observes its
result and plans again. It does not blindly run every operation: invalid intent
stops before context access, observations are cached, and hard policy blocks
skip history tools/features/model work. Max steps fail closed.

The state machine includes received, validating, gathering context, building
features, assessing anomaly, assessing risk, planning, waiting for human,
ready for execution, executing, blocked, completed and failed states. Invalid
transitions are rejected and terminal sessions cannot be reopened.

The model and planner have no signing, secret, shell or transfer authority.
Assessment stops at a guarded decision. A separate coordinator obtains explicit
human approval where necessary, calls the existing execution controller and
records feedback before the next event. The controller refreshes deterministic
preflight, preserves restrictions and prevents local replay. Ambiguous execution
errors are sanitized and never automatically retried.

Default memory is local/in-process. An optional JSON file persists audit outcomes
and mock reservations using owner-only permissions and atomic replacement.
Mock outcomes reduce demo available balance for later events but never create
settled history, recipient trust or automatic training samples. Tests use
temporary storage and verify repository fixtures are unchanged.

## Features and genuine local learning

`TransactionFeatures` defines 14 ordered finite numerical inputs: amount,
balance ratio, recipient count/frequency/average, relative recipient amount,
overall average/relative amount, daily spend, proposed-spend budget ratio,
new/trusted flags, optional elapsed recipient-payment time and missing-time flag.
Empty histories and zero balances are handled without division errors. Financial
values still use Decimal; floats are confined to numerical ML features.

`LocalAnomalyModel` defines fitting and local scoring. The default
`LocalKNNAnomalyModel` fits 128 synthetic normal vectors with seed 2048, learning
median/IQR scaling and nearest-neighbour reference behaviour. Scores are
normalized to [0,1] using leave-one-out reference distances and a conservative
demo calibration factor. Unusual example score (~0.941) exceeds the normal
example (~0.122). These are behavioural anomaly scores, not fraud probabilities.

Training never reads evaluation scenarios or expected outcomes. All references
are labelled synthetic/demo and have no fraud labels. The golden suite was used
as regression feedback during development, so this is not a held-out statistical
benchmark. No unsafe pickle files or trained binaries are stored. Scikit-learn
was absent; the standard-library model runs without installation or networking.
No optional Isolation Forest adapter was added.

Risk combines the learned score monotonically with original deterministic risk
signals. The learned model cannot lower pre-existing anomaly restrictions or
bypass hard financial policy. Bad model output or local failures block.

## Verification

Final local validation:

| Check | Result |
|---|---:|
| `python3 -m unittest discover -s tests -v` | 113 passed |
| `python3 -m unittest python/test_mandate_client.py -v` | 13 passed |
| `python3 -m unittest python/test_demo_ui.py -v` | 4 passed |
| `python3 -m ai_agent.cli eval` | 33/33 actions and risk flags correct |
| `python3 -m ai_agent.cli run-agent --source demo` | finite mock demo; review never auto-approved |
| `python3 -m unittest tests.test_privacy -v` | local assessment/demo/stdin/eval with networking disabled |
| `git diff --check` | clean |

The suite preserves financial schema, monotonic guardrail, allowlist, execution,
legacy-boundary and UI regression coverage. Obsolete provider tests were replaced
with deterministic parsing, local ML, state/planner, events, feedback, failure,
memory and privacy coverage. No tests send money or use external AI networking.

Computed golden metrics: scenario_count 33, action_accuracy 1.0,
unsafe_proceed_rate 0.0, human_review_rate 0.2121212121,
false_escalation_rate 0.0, policy_compliance_rate 1.0.
The original 30 safety cases remain represented, with obsolete provider scripts
replaced by local planner/malformed-input faults. Three cases add explicit
amount-first forms and max-step failure. Illegal planner tools now hard-block.
Metrics are computed from actual assessments, not hardcoded expected output.

Privacy tests deny socket creation/connect/DNS and external-service/legacy
imports while executing local workflows. Static checks reject network dependencies
and obsolete inference configuration in active AI code/config. Audit contains
public state/actions, normalized features and policy reasons, never raw history,
credentials or hidden reasoning. No actual credentials were added or committed.

## Reproduce

```bash
python3 -m ai_agent.cli run-agent --source demo
python3 -m ai_agent.cli run-agent --source stdin
python3 -m ai_agent.cli run-agent --source demo --non-interactive
python3 -m ai_agent.cli assess "Pay Charlie 0.6 CC for dinner" --interactive
python3 -m ai_agent.cli model-info
python3 -m ai_agent.cli eval
python3 -m unittest discover -s tests -v
python3 -m unittest python/test_mandate_client.py -v
python3 -m unittest python/test_demo_ui.py -v
python3 -m unittest tests.test_privacy -v
```

The offline demo does not move real Canton Coin. `WOULD_SUBMIT` means only a mock
handoff to the existing Daml boundary, not real authorization or settlement.

## Untested live and future work

No live Canton, LocalNet, DevNet, actual signatures, live history synchronization
or real-money transfer was run for this redesign. The separate previously tested
legacy flow remains frozen. No production fraud-detection or readiness claim is
made. Further work would require independent real-data validation, drift and
false-positive calibration, trusted fresh context, authenticated human approvals,
recipient identity mapping, encryption/retention, tamper-evident audits, durable
event deduplication, concurrency-safe reservations, restart/resume semantics and
reviewed settlement reconciliation. The host process remains a trusted boundary;
privacy tests are not an OS sandbox against arbitrary malicious local code.
