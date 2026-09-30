# Privacy model

All AI inference is local. No transaction context is sent to third-party AI
services. The agent has no inference transport, endpoint/key configuration,
provider factory, cloud SDK, model-server integration, or external model download.

The raw request, recipient identity, balance, transaction history, policy,
features, anomaly reference vectors, risk score, planner observations, and audit
records stay within local processing. The local model receives numerical features,
not signing credentials or raw history. No wallet data is sent to an external AI
provider. No external LLM is used.

## Separate trust boundaries

1. **Local AI:** explicit intent parsing, local files/context, read-only tools,
   learned distances, planning and deterministic guardrails. No outbound network
   access is used or permitted by this architecture.
2. **Human:** review binds to the specific assessment. Silence or rejection is
   not approval; a hard block cannot be overridden.
3. **Ledger execution:** the existing explicit execution controller and optional
   legacy Daml adapter. Canton networking occurs only at this boundary when
   separately enabled by trusted application code. Daml retains authority;
   existing settlement remains a separate legacy flow.

Offline/mock mode does not require Canton networking either. Tests replace socket
creation, connections and DNS with failures, deny external-service and legacy
imports, then run complete local assessment, autonomous demo, stdin and evaluation.
A static import test checks the local layer for network/service dependencies.
These checks validate this implementation; they are not an OS network sandbox
against an operator installing arbitrary malicious Python code.

## Local data and audit

Demo fixtures and synthetic anomaly reference data are explicitly illustrative.
They have no real financial identities or fraud labels. Evaluation scenarios are
not read by model training. Runtime training keeps numeric references in process;
no unsafe binary model loading is supported.

Structured audit output includes intent, features, learned score, policy/risk
signals, state transitions, public observation summaries, planner/guardrail action,
human decision and execution result. Raw transaction histories, credentials,
auth tokens, raw component exception strings and hidden chain-of-thought are
excluded. User-supplied purpose/recipient fields are still sensitive user data;
do not enter secrets there. Terminal capture, redirected stdout and explicitly
chosen memory files are under the operator's control, not a cloud log service.

Default memory is process-local. An explicit `--memory` path stores bounded JSON
audit records and demo reservations locally with owner-only permissions and
atomic replacement. No repository fixture is mutated. Do not put real sensitive
memory in a public repository or synced folder. OS permissions are not encryption;
local disk compromise, backups, terminal recording and operator exfiltration are
outside this prototype's guarantees. Production deployment needs encryption,
retention/deletion policy, access control and authenticated approvals.
