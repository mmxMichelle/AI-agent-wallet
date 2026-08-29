# Python Demo Layer

This folder contains the smallest Python pieces that make the GuardRail Wallet
demo work on real DevNet:

- `live_monitor.py` watches the Canton Ledger API and prints `PendingPayment`
  and `TransactionRecord` activity in real time.
- `mandate_client.py` creates Mandate proposals, approves or rejects high-value
  payments, and settles approved payments through the existing Cantor8 toolkit.

The goal is simple:

```text
Small payment  -> auto-approved -> settled immediately
Large payment  -> human approval -> then settled
```

## What viewers should notice

1. The Daml `Mandate` enforces policy.
2. Python observes the ledger and turns contract activity into readable output.
3. Canton Coin movement is real on DevNet.

## Quick Demo Flow

### Scenario 1: Small payment

- Set a low threshold, for example `0.20 CC`
- Request `0.10 CC`
- The policy decision is `AUTO APPROVED`
- The payment settles right away
- The live monitor shows the resulting ledger events

### Scenario 2: Large payment

- Keep the same threshold, for example `0.20 CC`
- Request `0.50 CC`
- The policy decision is `HUMAN APPROVAL REQUIRED`
- The payment pauses until the owner clicks `Approve`
- After approval, the payment settles
- The live monitor shows the approval trail and settlement

## Requirements

Use the same Cantor8 environment variables as `c8lab.py`:

```bash
export C8_BASE=https://api.validator.dev.digik.cantor8.tech/api/ledger
export C8_IDP=https://auth.dev.digik.cantor8.tech
export C8_CLIENT_ID=hackathon
export C8_CLIENT_SECRET=...
```

The monitor uses the WebSocket update stream and standard Python plus the
`websocket-client` package.

## Run the monitor

```bash
python3 python/live_monitor.py --from-now --party <FULL_PARTY_ID>
```

Useful options:

```bash
python3 python/live_monitor.py --debug-protocol
python3 python/live_monitor.py --reconnect-seconds 1.5
python3 python/live_monitor.py --state-file python/monitor_state.json
```

## Run the Mandate client

```bash
python3 python/mandate_client.py parties
python3 python/mandate_client.py packages
python3 python/mandate_client.py upload-dar --dar daml-starter/.daml/dist/daml-starter-0.0.1.dar
python3 python/mandate_client.py create-proposal \
  --owner <OWNER> \
  --spender <SPENDER> \
  --allowed-recipient <RECIPIENT> \
  --cap 2.00 \
  --approval-threshold 0.20 \
  --expires-at 2026-08-30T00:00:00Z
python3 python/mandate_client.py settle \
  --from-party <SPENDER> \
  --to-party <RECIPIENT> \
  --amount 0.50
```

## How it works

- `PendingPayment` means the spending request needs a human decision.
- `TransactionRecord` is the audit trail for auto-approval, owner approval, or
  rejection.
- `settle` reuses `c8lab.transfer(...)` so the real Canton Coin move follows the
  existing Cantor8 token path.
- If the transfer comes back as `offer`, the receiver must accept manually.

## Live monitor output

The monitor prints a human-readable timeline instead of raw ledger JSON. It is
designed to make the demo obvious in a room:

- payment requested
- policy decision
- approval or rejection
- Canton settlement
- completed payment

## Important note

This code does not enforce policy by itself. The Daml `Mandate` does that.
Python only drives the demo and observes the ledger.
