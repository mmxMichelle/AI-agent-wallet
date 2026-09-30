# AI agent architecture

The extension is standard-library Python and is isolated in `ai_agent/`.
The original `python/`, `c8lab.py`, and `daml-starter/` are frozen.
The original offline UI is preserved and is a future integration point, not
a dependency of this CLI.

```text
Untrusted request -> Provider -> strict JSON -> grounded PaymentIntent
                                                   |
Trusted context snapshot + full policy ------------+----+
                                                   |    |
                                                   v    |
                                      GovernedAgent     |
                                      bounded tool loop |
                                       |                |
                 read-only allowlist --+                |
                 balance/history/policy/risk            |
                                       |                |
                                       v                v
                                Recommendation -> Guardrail
                                                       |
                                            immutable Assessment
                                                       |
                                      explicit ExecutionController
                                      fresh context + guardrail
                                      block / wait / human decision
                                                       |
                                    +------------------+----------------+
                                    v                                   v
                              Mock recorder                    Optional legacy adapter
                              no state change                  existing Mandate commands
                                                                       |
                                                          Existing owner approval and
                                                          settlement remain separate
```

## Components and choices

| Module | Responsibility |
|---|---|
| `models.py` | Frozen dataclasses, actions, Decimal validation, strict JSON |
| `providers.py` | Provider Protocol, central factory, mock, OpenAI-compatible and Ollama transports |
| `parser.py` | Validate output and ground recipient/amount/currency/purpose in request |
| `memory.py` | Context Protocol and JSON snapshot repository |
| `policy.py`, `retrieval.py` | Validated DEMO thresholds and stable token overlap retrieval |
| `risk.py` | Recipient statistics and deterministic anomaly indicators |
| `tools.py` | Five explicitly allowlisted, snapshot-bound read-only tools |
| `orchestrator.py` | Bounded model/tool dialogue, recommendation, mandatory guardrail |
| `guardrail.py` | Hard blocks, review rules, monotonic combination |
| `ledger.py` | Separate execution controller and mock recorder |
| `legacy_adapter.py` | Disabled-by-default lazy wrappers around legacy functions |
| `logging_utils.py` | Allowlisted JSON audit records |
| `cli.py`, `evaluation.py` | Offline demos and reproducible golden evaluation |

Small explicit modules make the trust boundaries inspectable without an agent
framework, vector database, SDK, or trained anomaly model. Immutable dataclasses
keep an assessment tied to its parsed intent. Money and ratios use Decimal;
evaluation rates use ordinary numerical ratios, not monetary floats.

## Data flow and agent boundary

The provider receives system instructions and separately encoded untrusted user
data. Strict JSON rejects duplicate keys, non-finite constants, fences, trailing
text, unknown fields, and invalid types. Domain validation rejects empty or
ambiguous recipients, unsupported currency, invalid confidence, and nonpositive
amounts. A deterministic grounding check prevents a provider from changing the
recipient, amount, currency, or purpose. Unsupported language must clarify.

The loop accepts either a validated tool request or a validated recommendation.
Tool arguments must be exactly `{}`: tools use the already bound intent/context.
No model argument can specify paths, override history, or change policy. At most
six tools can run, followed by one final model response (seven loop responses
maximum, plus the intent parsing response). Protocol errors, provider errors,
unknown tools, and exhaustion escalate with zero confidence. Invalid intents
block before tools. Context/configuration failures abort without execution.

Retrieval returns five ranked excerpts with references. All policy fields remain
available to the deterministic guardrail even when absent from retrieval. The
agent can choose a different tool order or finish early; guardrail safety does
not depend on the agent collecting evidence correctly.

Context stores balance, daily spend, and timestamped transaction fixtures.
Recipient count, averages, new/trusted status, and relative amounts are computed
from that snapshot. Demo history is explicitly illustrative, not ledger evidence.
Repeated-spend evaluation supplies accumulated daily spend in a fresh fixture;
mock submissions do not manufacture settled transaction history.

## Policy and execution boundaries

Supplemental AI policy controls whether this application should hand a request
to Daml. It cannot authorize ledger spending. Daml Mandate choices retain their
original signatories/controllers, recipient restriction, threshold, expiry,
and cap behavior. The extension does not fix or redesign existing contracts.

The final action is `max(model action, deterministic action)` by restriction:
proceed < review < block. A human confirmation permits a reviewed request to
reach the execution controller, but never changes a hard block into approval.
The controller refreshes context and reruns preflight before submission. It
consumes successful/declined attempts within its process to avoid local replay.

`LegacyDamlPaymentExecutionAdapter` requires explicit enablement, a trusted
Mandate CID, spender party, threshold, and exact recipient-to-party mapping.
It calls existing `charge_command` or `request_high_value_command` and
`submit_command`. Daml validates the actual choice regardless of the configured
threshold. This one-shot adapter neither approves nor settles. After submission,
existing tooling must resolve new contract IDs and perform owner approval and
settlement. This avoids recreating the tested settlement logic. The legacy
wallet adapter obtains unlocked Amulet holdings through `c8lab.holdings`; history
and daily spend must be supplied by the trusted caller. That incomplete live
context integration is one reason no live execution CLI is provided.

## Bring Your Own Model / Bring Your Own Key

GuardRail Wallet has no maintainer-paid inference requirement. Users own their
credentials and explicitly choose `mock`, `openai-compatible`, or `ollama`.
The default remains offline, deterministic mock; model/key/endpoint presence
alone never selects an external provider. Evaluation always uses mock.

`providers.create_provider(provider_name=None, model=None, base_url=None)` is
the central selection/configuration layer. CLI arguments override environment
variables, which override safe defaults. `LLM_PROVIDER` defaults to `mock`.
Generic APIs use `LLM_BASE_URL`, `LLM_MODEL`, and environment-only `LLM_API_KEY`.
Ollama uses `OLLAMA_BASE_URL` (default `http://localhost:11434`) and
`OLLAMA_MODEL`, and never forwards `LLM_API_KEY`. There is no default model.
No secrets belong in config files; `.env.example` is reference-only and `.env`
is ignored, not automatically loaded. No vendor SDK or paid dependency is added.

The existing `LLMProvider.complete(messages) -> str` Protocol is preserved.
Both HTTP adapters normalize their vendor envelope into bounded JSON text before
it reaches the agent. The provider rejects malformed envelopes, incomplete
responses, vendor tool calls, and non-JSON content. Strict downstream schema
validation, grounding, tool allowlisting, risk computation, and deterministic
guardrails still run. Parser, orchestrator, tools, and guardrail require no
provider-specific logic. All models have identical restricted privileges.

OpenAI-compatible mode supports hosted APIs and user-run local servers such as
LM Studio. Ollama uses `/api/chat` with JSON format and streaming disabled.
Local models can avoid hosted API charges but require user-provided compute,
model availability, and appropriate hardware. Nothing starts servers, installs
software, or downloads weights automatically.

CLI provider/environment selection is explicit opt-in to sending context; no
provider is autodetected and failures never fall back. Network requests have a
20-second socket timeout, 64-KiB response envelope limit, 10,000-character content
limit, disabled redirects/proxies, and HTTPS except for explicit loopback hosts.
Generic non-loopback endpoints require a user API key; local compatible servers
may omit it. Transport/error bodies are not surfaced. Provider failure at intent
parsing blocks; failure during recommendations triggers existing human escalation,
with hard deterministic blocks still enforced. Execution authority is unchanged.

Live Canton adapters require separate explicit construction/enablement; importing
them does not import the legacy runtime. Tests use fake runtime functions and a
subprocess that forbids legacy imports and networking. No Canton, DevNet, remote
LLM, owner-signature, or real settlement integration was verified in this work.
