# GuardRail Wallet

The original wallet documentation below is preserved. For the optional governed
AI extension and its offline quickstart, see [AI Agent Extension](#ai-agent-extension).

GuardRail Wallet is a Canton / Daml demo that shows how an autonomous agent can
request payments, get human approval when needed, and settle on real Canton Coin
on DevNet.

The demo is built to be obvious in a live presentation:

- small payments go through automatically
- larger payments pause for human approval
- every important action appears in the live monitor
- real Canton Coin moves on DevNet

The core idea is simple:

- the Daml `Mandate` contract sets the spending rules
- the Python live monitor watches `PendingPayment` and `TransactionRecord`
- the Python demo client submits approvals and settlement
- `c8lab.py` reuses the Cantor8 toolkit for authentication, parties, registry,
  and token transfers

Final demo flow:

```text
RequestHighValue
  -> PendingPayment
  -> owner Approve / Reject
  -> TransactionRecord
  -> Python settle
  -> c8lab.transfer(...)
  -> real Canton Coin movement
```

## Demo in one glance

| Scenario | Amount | Policy outcome | Ledger result |
|---|---:|---|---|
| Small payment | `0.10 CC` | `AUTO APPROVED` | Settles immediately |
| Large payment | `0.50 CC` | `HUMAN APPROVAL REQUIRED` | Waits for owner approval, then settles |

## Demo

🎥 [Watch the GuardRail Wallet demo](demo/GuardRail-Wallet-How-It-Works.mp4)

The demo shows two cases:

- **Small payment:** below the approval threshold → automatically approved and settled.
- **Large payment:** above the approval threshold → paused until explicit human approval.

1. GuardRail Wallet enforces a spending policy in Daml.
2. Small payments are automatic.
3. Large payments wait for human approval.
4. Approved payments are settled on real Canton Coin.
5. The live monitor shows the resulting ledger events.

## What is in this repo

| File | What |
|---|---|
| `CHALLENGES.md` | The original hackathon prompts |
| `SETUP.md` | LocalNet setup and the Daml toolchain |
| `API.md` | Tested API cheat sheet |
| `TROUBLESHOOTING.md` | The failures we actually hit and how to fix them |
| `c8lab.py` | The shared Cantor8 toolkit |
| `python/` | Live monitor, Mandate client, and demo UI helpers |
| `daml-starter/` | Working Daml package for the mandate flow |

If you are trying to reproduce the demo, start with `SETUP.md`.

**Looking for the problems?** They are in [`CHALLENGES.md`](CHALLENGES.md).

## How it works

1. Create a mandate with a spending cap and approval threshold.
2. Request a small payment and let it auto-approve.
3. Request a larger payment and pause for human approval.
4. Settle the approved payment on Canton Coin.
5. Watch the live monitor print the resulting ledger activity.

This repo is intentionally small: the Daml model enforces policy, and Python
orchestrates the demo and observes the ledger. It does not add an LLM, frontend,
or custom settlement engine.

## Tooling

`c8lab.py` is Python 3, **stdlib only**, no `pip install`. That is deliberate:
some laptops are locked down and you do not want to debug pip on the day.

It runs against two targets:

- **LocalNet**, a whole Canton network in Docker on your laptop. The default.
- **DevNet**, the shared Cantor8 node. Set four environment variables.

## The lab

Six steps. This is the shape of every Canton app.

```
1. Get a token                    the API is authenticated
2. Allocate a party               your identity on the ledger
3. Set up a TransferPreapproval   so people can pay you directly
4. Read your balance from the ACS zero, at first
5. Get some Canton Coin           LocalNet mints it, on DevNet ask the team
6. Send a token standard transfer to another party
```

### Run it

```bash
python3 c8lab.py                          # check everything, list parties, balances
python3 c8lab.py party myteam             # step 2
python3 c8lab.py preapproval <party>      # step 3
python3 c8lab.py holdings <party>         # steps 4 and 5
python3 c8lab.py transfer <from> <to> 25  # step 6
python3 c8lab.py accept <instructionCid> <to>   # if step 6 returned an offer
python3 c8lab.py grant <user> <party>           # fix a 403
```

`check` first, always. It verifies auth, the ledger, your parties and their
balances. It does **not** check that the registry is reachable, that you have
act-as rights on every party, or that a preapproval has been accepted. So a
clean `check` means the basics are fine, not that everything is.

### What good output looks like

```
base       http://localhost:2975
mode       LocalNet / unsafe HS256
token      ok
ledger end 104
local parties (3):
    app_user_cantor8-hackathon-1::1220...
    participant::1220...

holdings for app_user_cantor8-hackathon-1: 1 contract(s), total 4220.16
    {'amount': '4220.16', 'instrument': 'Amulet', 'locked': False}
```

`Amulet` is Canton Coin. Amulet is the name in the Daml code, Canton Coin is the
name in the marketing. Same thing.

On LocalNet the balance grows on its own as mining rounds tick over and pay the
validator. Nothing is broken.

## Three things worth understanding

### Your balance is not a number

It is a set of contracts. `total 4220.16` is the sum of the `Holding` contracts
you can see. A transfer archives the ones it spends and creates new ones, like
handing over a note and getting change.

This is why two transfers at the same time can fight over the same holding.
One wins, the other fails, and both pay for the traffic.

### A token is a Daml package plus a web service

Step 6 is two phases, and the first surprises everyone:

```
1. Ask the registry for a transfer factory and a choice context.
2. Exercise TransferFactory_Transfer, attaching what it gave you.
```

Why the registry exists: privacy. You cannot see the issuer's configuration
contracts, so it hands them to you as **disclosed contracts**, valid for that one
transaction. On LocalNet the registry is the scan app; ours returned five
disclosed contracts and a context with `amulet-rules`, `open-round`,
`transfer-preapproval` and `external-party-config-state`.

If you skip this and try to build the transfer by hand, it will not work, and
the error will not tell you why.

### `transferKind` tells you which flow you are in

The registry answers with one of:

- **`direct`**: the receiver has a live `TransferPreapproval`. Money moves
  immediately.
- **`offer`**: no preapproval. A `TransferInstruction` is created and the
  receiver has to accept it. Their balance does **not** change until they do.
- **`self`**: sender and receiver are the same party.

We saw both. A party with an accepted preapproval got `direct` and received the
money straight away. A party with no preapproval got `offer`, the transfer
succeeded, and the balance stayed empty until we accepted it.

`transfer` prints the `instructionCid` and the exact accept command when it
returns an offer. Run it and the money moves.

**So if you send money and the receiver sees nothing, check `transferKind`
before you debug anything else.** Preapproval acceptance is not instant: you
create the proposal, and the validator's automation accepts it a moment later.

## The functions

Import it, do not just use the CLI.

| Function | Does |
|---|---|
| `token(sub)` | HS256 on LocalNet, Keycloak on DevNet |
| `call(path, body, sub)` | Any Ledger API call. Prints the real error on failure. |
| `ledger_end()` | Current offset |
| `parties()` / `local_parties()` | What the node knows, and what it hosts |
| `allocate_party(hint)` | Allocate, or reuse if it exists |
| `grant_act_as(user, party)` | Fix a 403 |
| `holdings(party)` | Balances, via the interface filter |
| `submit(cmds, act_as, disclosed)` | Any command, with disclosed contracts |
| `create_preapproval(me, provider)` | Step 3 |
| `registry(path, body)` | Call the token registry |
| `transfer(from, to, amount)` | Step 6, both phases |
| `check()` | Run this first when something is broken |

Only reuse parties where `isLocal` is true. A node lists parties it has heard
about from the network, including ones hosted elsewhere that it cannot submit
for. Using one of those gives you
`NO_SYNCHRONIZER_ON_WHICH_ALL_SUBMITTERS_CAN_SUBMIT`.

## Running against DevNet

```bash
export C8_BASE=https://api.validator.dev.digik.cantor8.tech/api/ledger
export C8_IDP=https://auth.dev.digik.cantor8.tech
export C8_CLIENT_ID=hackathon
export C8_CLIENT_SECRET=<ask the Cantor8 team>
export C8_REGISTRY=<registry base url>       # needed for transfers
python3 c8lab.py check
```

Setting `C8_IDP` switches from a self-signed LocalNet token to a real Keycloak
client-credentials token. Everything else is the same.

For DevNet you will also need `C8_REGISTRY` pointing at the Cantor8 registry, and
Canton Coin has to be sent to you: give the team your party ID.

**Not yet verified on DevNet.** Party allocation there may need the
external-party topology flow rather than `POST /v2/parties`. If it fails at step
2, that is why.

## Docs

```
Canton docs, has a chatbot   https://docs.canton.network
Ledger API                   https://docs.canton.network/sdks-tools/api-reference/ledger-api
Validator Admin API          https://docs.canton.network/sdks-tools/api-reference/admin-api
Token standard               https://docs.canton.network/appdev/deep-dives/token-standard
```

## AI Agent Extension

**GuardRail Wallet — Governed AI Payment Agent** adds a separate, optional Python
package to the original wallet. The original architecture described above remains
the execution layer: Daml Mandate choices authorize requests, and the existing
Python client coordinates owner approval and separate Canton settlement.
All existing Python files, Daml contracts, and `c8lab.py` are unchanged. In
particular, `python/demo_ui.py --offline-demo` retains its existing behavior.
The new CLI coexists with that demo; it does not require or modify its UI.

```text
User request
    |
    v
Intent Parser (untrusted JSON -> validation -> grounded intent)
    |
    v
Tool-Using Agent (bounded loop, read-only allowlist)
    |
    +--> Local policy retrieval
    +--> Transaction / recipient history
    +--> Balance snapshot
    +--> Deterministic risk signals
    |
    v
AI Recommendation
    |
    v
Deterministic Guardrail
    |
    +--> Block
    +--> Human Review (explicit yes/no)
    +--> Execution Controller (fresh preflight)
                 |
                 +--> Mock: "Would submit to existing Daml Mandate"
                 |
                 +--> Optional existing Daml Mandate submission
                              |
                              v
                      Existing Approval / Settlement Flow
                      (separate, not invoked by the AI extension)
```

Probabilistic AI proposes. Deterministic software validates. Daml remains
authoritative. Humans remain in control when required. An LLM never receives
transfer, settlement, approval, ledger-write, shell, filesystem, or HTTP tools.

The parser accepts explicit requests such as `Pay Alice 0.1 CC for dinner`.
Provider output must be strict JSON, pass domain validation, and match the
explicit request fields. Money uses `Decimal`, never binary floats. This first
version deliberately supports a limited `Pay/Send RECIPIENT AMOUNT CC for PURPOSE`
grammar even with remote inference. Missing/ambiguous values and percentage
requests require clarification; they never silently acquire an amount or currency.

The agent selects from five read-only tools and has a six-tool-call budget.
The offline provider is a deterministic test double; the same loop accepts an
optional remote provider. Policy retrieval uses local token overlap, with stable
policy references. JSON demo history supplies recipient counts and averages.
Deterministic risk signals cover balance fraction, spending, unusual amounts,
new recipients, blocked categories, and insufficient funds. The anomaly score is
a transparent weighted heuristic, not a validated fraud detection model.

The full supplemental policy always runs after the recommendation, regardless of
which tools the model used. Hard rules block; review rules and low confidence
escalate. The final action is the more restrictive of model and guardrail actions:
`PROCEED_TO_DAML < REQUIRE_HUMAN_CONFIRMATION < BLOCK_PRE_LEDGER`.
Neither a human yes nor model instructions can override a hard preflight block.
These DEMO preflight policies do not replace or alter the existing Daml Mandate.

### Offline quickstart

From this repository, with Python 3.10+ and no additional packages:

```bash
python3 -m ai_agent.cli parse "Pay Alice 0.1 CC for coffee"
python3 -m ai_agent.cli assess "Pay Alice 0.05 CC for coffee"
python3 -m ai_agent.cli assess "Pay Charlie 0.6 CC for dinner"
python3 -m ai_agent.cli assess "Pay Charlie 0.6 CC for dinner" --interactive
python3 -m ai_agent.cli assess "Pay UnknownXYZ 0.9 CC for dinner"
python3 -m ai_agent.cli assess "Send 90% of my balance to UnknownXYZ"
python3 -m ai_agent.cli demo
python3 -m ai_agent.cli eval
python3 -m unittest discover -s tests -v
python3 -m unittest python/test_mandate_client.py -v
python3 -m unittest python/test_demo_ui.py -v
```

The percentage request returns a clarification error with a nonzero CLI exit
status. Plain `assess` never executes. Optional `assess --interactive` prompts
for `yes`/`no` when human review is required and uses only mock execution;
no real Canton Coin is moved. Rejection records `REJECTED_BY_HUMAN`; empty,
unrecognized input or EOF leaves review pending. Payments allowed to proceed
need no approval prompt, and blocked payments cannot be overridden.
`demo` asks for explicit `yes`/`no` on review;
empty input or EOF leaves the request waiting. Each scenario uses the same demo
snapshot, and mock submission does not change balances or claim settlement.
CLI assessment/demo output includes JSON-compatible audit records on stdout.
No audit files or credentials are automatically persisted.

**The offline AI demo does not move real Canton Coin.** No Canton, Docker,
DevNet, internet access, coin, or API key is needed for the offline extension.

### Evaluation and optional integration

The checked-in 30-scenario golden suite exercises the actual offline pipeline.
Measured on 2026-09-30: action accuracy **100%**, unsafe proceed rate **0%**,
human review rate **26.67%**, false escalation rate **0%**, policy compliance
rate **100%**. Definitions, denominators, and limitations are in
[EVALUATION.md](docs/EVALUATION.md). These are fixture results, not model quality
or deployment guarantees. All 85 AI tests (65 existing plus 20 provider tests), 13 mandate tests, and
4 demo UI tests passed locally. The original AI suite also passes with networking
disabled; HTTP provider tests use fake transports.

The isolated legacy adapters lazily wrap existing holdings and Mandate command
functions. They are disabled by default and are not exposed as live CLI execution.
Future integration needs trusted party/contract resolution, fresh complete
history, authenticated owner decisions, and reviewed reconciliation with the
existing settlement flow. Neither LocalNet nor DevNet was re-verified for this
extension, and no new live financial calls were made.

This is a research / portfolio / hackathon-derived prototype, not production-ready
financial software. Context is a static demo snapshot; category matching is
literal, names are not identity verification, audit output is not tamper-evident,
and replay prevention is only local to a controller instance. See
[architecture](docs/AI_AGENT_ARCHITECTURE.md), [safety model](docs/SAFETY_MODEL.md),
and [implementation report](IMPLEMENTATION_REPORT.md).


## Choose Your LLM

GuardRail Wallet is model-agnostic. It runs fully offline with a deterministic
mock provider by default and allows users to bring their own hosted or local
LLM. The repository maintainer does not need to supply or pay for an LLM API.
Credentials belong to the user (Bring Your Own Model / Bring Your Own Key).
No paid dependency, model, API key, internet connection, or Canton runtime is
required for the default mode, tests, or golden evaluation.

```text
User-selected LLM
        |
        v
LLMProvider abstraction
        |
        v
GuardRail Agent
        |
        v
Deterministic Safety Layer
        |
        v
Existing Daml Boundary
```

Changing the LLM does not change the safety boundary. Every response is untrusted
and must pass strict JSON parsing, schema validation, the read-only tool
allowlist, risk computation, and deterministic guardrails. Models have identical
restricted privileges; human approval and Daml authority remain unchanged.
The CLI still uses demo context and mock execution, regardless of provider.

List modes:

```bash
python3 -m ai_agent.cli providers
```

**1. Mock (default): offline, deterministic, free to run; suitable for testing and evaluation.**

```bash
python3 -m ai_agent.cli assess "Pay Alice 0.05 CC for coffee"
python3 -m ai_agent.cli assess "Pay Alice 0.05 CC for coffee" --provider mock
python3 -m ai_agent.cli eval
```

**2. Generic OpenAI-compatible hosted API (optional).** Choose an endpoint and
model from your provider. Replace the placeholders below. Supply your own key
through the environment or a secret manager; never put a key in CLI arguments,
source files, or Git. For example, in Bash/Zsh, read it without echo or history:

```bash
export LLM_BASE_URL="https://YOUR_PROVIDER_HOST/v1"
export LLM_MODEL="USER_MODEL_NAME"
read -rs LLM_API_KEY
export LLM_API_KEY
python3 -m ai_agent.cli assess "Pay Alice 0.05 CC for coffee" --provider openai-compatible
```

The endpoint must support chat completions with JSON response format. There is
no fixed vendor, endpoint, or model name. Provider charges and availability are
the user's responsibility; third-party APIs are not claimed to be free.

**3. Ollama / local model (optional).** Install Ollama yourself if desired, start
the server, then choose and download a model yourself. In one terminal:

```bash
ollama serve
```

In another terminal, replace `USER_LOCAL_MODEL` with your chosen model:

```bash
ollama pull USER_LOCAL_MODEL
python3 -m ai_agent.cli assess "Pay Charlie 0.6 CC for dinner" --provider ollama --model USER_LOCAL_MODEL
```

Alternatively set `OLLAMA_MODEL`. `OLLAMA_BASE_URL` defaults to
`http://localhost:11434`. No API key is sent in Ollama mode. GuardRail Wallet
never installs Ollama, starts a server, or downloads weights. Local inference
can avoid hosted API charges, but uses your hardware and electricity; model
availability and hardware requirements depend on your choice. The adapter uses
Ollama's non-streaming JSON [chat API](https://docs.ollama.com/api/chat).

**4. LM Studio or another local OpenAI-compatible server (optional).** Start your
chosen server and load a model yourself. Replace the model placeholder:

```bash
unset LLM_API_KEY
export LLM_BASE_URL="http://localhost:1234/v1"
python3 -m ai_agent.cli assess "Pay Alice 0.05 CC for coffee" --provider openai-compatible --model USER_LOCAL_MODEL
```

The project does not need to identify the backend. A loopback endpoint may omit
the API key; a non-loopback OpenAI-compatible endpoint requires a user key and
HTTPS. HTTP is allowed only for explicit loopback hosts (`localhost`, loopback
IP addresses). Redirects and ambient HTTP proxies are disabled so credentials
stay with the configured endpoint.

Configuration precedence is **CLI arguments > environment > safe defaults**:
`--provider` / `LLM_PROVIDER` / `mock`; `--model` / `LLM_MODEL` or `OLLAMA_MODEL`;
`--base-url` / `LLM_BASE_URL` or `OLLAMA_BASE_URL`. There is no default model or
hosted endpoint. Setting just a key, endpoint, or model never activates external
inference. Explicit selection via `--provider` or `LLM_PROVIDER` authorizes
sending request and demo context to that endpoint without another inference
prompt; payment approval requirements remain unchanged. `--provider mock`
overrides external environment selection, and `eval` always uses mock.

`.env.example` is a placeholder reference. `.env` is ignored and is **not loaded
automatically**; export variables in your shell. Secrets are environment-only;
there is no key CLI flag or config-file loader. Unavailable providers, missing
configuration, and malformed responses fail closed without fallback to another
provider. Invalid intent blocks; failure during recommendation escalates to
human review while deterministic hard blocks still apply. Provider errors are
sanitized, and credentials are excluded from audit records. Automated tests use
fake HTTP transports; no live hosted or local model integration is claimed.
