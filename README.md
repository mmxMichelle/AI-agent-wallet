# GuardRail Wallet
## Privacy-Preserving Autonomous AI Payment Agent

GuardRail Wallet is a local-first autonomous payment agent combining deterministic
payment-intent parsing, an observe-plan-act loop, transaction-context analysis,
local unsupervised anomaly detection, deterministic financial guardrails,
human-in-the-loop escalation, and existing Daml/Canton execution controls.

**No wallet data is sent to an external AI provider.** No external LLM is used.
All assessment, features, learning, planning, and audit processing stay local.
This is a portfolio prototype, not production financial software or a validated
fraud detector. **The offline demo does not move real Canton Coin.**

Observe locally. Learn locally. Plan locally. Enforce deterministically.
Escalate to humans when required. Keep payment authority outside the AI.

```text
Payment Event
    |
    v
Local Parser
    |
    v
Autonomous State Machine
    |
    +--> Balance
    +--> Recipient / Transaction History
    +--> Local Policy
    |
    v
Feature Engineering
    |
    v
Local ML Anomaly Model
    |
    v
Risk Engine
    |
    v
Autonomous Planner
    |
    v
Deterministic Guardrail
   /        |        \
BLOCK     HUMAN     PROCEED
                      |
                      v
                Daml Boundary
                      |
                      v
          Existing Canton Settlement
```

### Run locally

Python 3.10+ and the standard library are sufficient. No downloads, API keys,
model servers, or Canton runtime are required for these commands:

```bash
python3 -m ai_agent.cli assess "Pay Alice 0.05 CC for coffee"
python3 -m ai_agent.cli assess "Pay Charlie 0.6 CC for dinner" --interactive
python3 -m ai_agent.cli run-agent --source demo
python3 -m ai_agent.cli run-agent --source stdin
python3 -m ai_agent.cli model-info
python3 -m ai_agent.cli eval
```

The demo is finite. Low-risk events can reach the mock execution controller
without a prompt. Review pauses in `WAITING_FOR_HUMAN`: `yes` permits a guarded
mock submission; `no` produces `REJECTED_BY_HUMAN`; EOF, blank, or an unknown
answer leaves it waiting without execution. Hard blocks never ask for approval.
For noninteractive demonstrations use:

```bash
python3 -m ai_agent.cli run-agent --source demo --non-interactive --max-events 3 --max-steps 20
```

Local JSONL input has one `{"request": "Pay Alice 0.05 CC for coffee"}` per line:

```bash
python3 -m ai_agent.cli run-agent --source jsonl --file /path/to/events.jsonl --memory /path/to/local-demo-memory.json
```

Memory is optional, local, and sensitive. Each completed mock handoff reserves
its amount in demo memory for subsequent events; this is **not settlement** and
does not manufacture recipient history or retrain on unverified transactions.
Use a fresh memory file for a fresh demo. Fixtures are read-only. Audit output is
printed locally; an explicitly selected memory file retains outcomes using JSON
and owner-only file permissions. No memory file is created by default.

### Why no LLM?

This financial-agent design prioritizes confidentiality, deterministic behaviour,
auditability, reproducibility, and fail-closed semantics over unrestricted
natural-language reasoning. An agent is perception/context + memory + tools +
local learning + planning + state + guarded action + outcome feedback.

The planner inspects missing observations on each iteration, selects an allowed
local action, observes its result, and updates state. Invalid intent stops before
wallet-context access. Cached observations are not fetched again. Hard policy
blocks skip unnecessary history tools and anomaly inference. A step budget
prevents unbounded work. Execution is outside the model and tool registry.

Supported explicit grammar (case-insensitive verbs/currency):

- `Pay Alice 0.1 CC for coffee`
- `Send Alice 0.1 CC for coffee`
- `Send 0.1 CC to Alice for coffee`
- `Transfer 0.1 CC to Alice for coffee`
- `Pay Alice 0.1 CC`

Names are explicit ASCII identifiers (multiword names allowed). Money uses
Decimal. The parser preserves purpose text. Percentages, missing currency,
approximate amounts, alternatives, and inferred recipients produce
`CLARIFICATION_REQUIRED` and block before execution. It never guesses.

### Local learning and safety

`LocalKNNAnomalyModel` fits 128 deterministic synthetic normal reference vectors
(seed 2048), separate from the golden scenarios. It uses robust feature scaling
and nearest-neighbour distances to produce a behavioural anomaly score in [0,1].
No fraud labels, trained binary artifacts, or unsafe pickle files are used.
Scikit-learn is not installed or required; no optional adapter is active.

Fourteen features describe amount, balance ratio, recipient count/frequency,
recipient/overall averages and relative amounts, daily spend and budget ratio,
new/trusted status, and optional time since last recipient payment with a missing
indicator. Numerical ML features use floats; financial policy still uses Decimal.

The learned score can only add restriction to existing deterministic risk signals.
Insufficient balance, hard caps, balance-fraction limits, and blocked categories
remain hard blocks. The final decision is the more restrictive of planner proposal
and guardrail. Human approval cannot override a hard block. Canton authority and
existing settlement semantics are unchanged; there is no live execution CLI.

### Validation and limits

The local test suite covers parser ambiguity, model fitting/determinism, feature
edge cases, adaptive planning, state transitions, finite events, memory isolation,
human decisions, guardrails, and privacy with socket networking disabled.
The original 13 mandate and 4 UI regressions remain required. The 33-scenario
golden suite reports computed action accuracy, unsafe proceed rate, human review
rate, false escalation rate, and policy compliance; these are fixture metrics,
not general AI accuracy or real-money validation.

Read [architecture](docs/AI_AGENT_ARCHITECTURE.md), [privacy](docs/PRIVACY_MODEL.md),
[safety](docs/SAFETY_MODEL.md), [evaluation](docs/EVALUATION.md), and the
[implementation report](IMPLEMENTATION_REPORT.md). No live Canton, DevNet, or
real-money transfer was run for this redesign. The existing live wallet layer
below is separate from the fully local AI demo.

## Legacy Daml/Canton wallet (frozen)

The following documentation describes the previously tested wallet. Its code,
contracts, signing authority, and settlement commands were not changed by the
local-agent extension. Canton networking requires explicit legacy execution.

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
