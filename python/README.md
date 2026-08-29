# Python Live Monitor

This monitor watches the Canton Ledger API for new `Mandate.PendingPayment`
and `Mandate.TransactionRecord` contract creations and prints them to the
terminal in real time.

## What it does

It follows ledger updates for the parties you specify, filters for the mandate
contracts, and turns those ledger events into readable terminal alerts.

It does not enforce policy. The Daml contract enforces the mandate rules.

## Architecture

```text
AI Agent / client
      ↓
Canton Ledger API
      ↓
Daml Mandate
      ↓
PendingPayment / TransactionRecord
      ↓
Python Live Monitor
      ↓
Terminal alert
```

## Requirements

Set the same Cantor8 environment variables used by `c8lab.py`:

```bash
export C8_BASE=https://api.validator.dev.digik.cantor8.tech/api/ledger
export C8_IDP=https://auth.dev.digik.cantor8.tech
export C8_CLIENT_ID=hackathon
export C8_CLIENT_SECRET=...
```

You also need to tell the monitor which parties to watch:

```bash
python3 python/live_monitor.py --party <party-id>
```

You can repeat `--party` for multiple parties.

## Run

```bash
python3 python/live_monitor.py --party <party-id>
```

Useful options:

```bash
python3 python/live_monitor.py --party <party-id> --from-now
python3 python/live_monitor.py --party <party-id> --poll-seconds 1.5
python3 python/live_monitor.py --party <party-id> --state-file python/monitor_state.json
```

## Resume and checkpointing

The monitor stores the last processed ledger offset in
`python/monitor_state.json`.

On startup it:

1. Loads the saved offset if present.
2. Falls back to the current ledger end if no checkpoint exists, unless
   `--from-now` is set.
3. Updates the checkpoint only after a ledger update has been processed.

The checkpoint file is written atomically.

## Contract meaning

- `PendingPayment` means a high-value charge has been requested and still
  needs owner approval.
- `TransactionRecord` is the audit trail for a processed charge, approval, or
  rejection.

Current statuses:

- `AUTO_APPROVED`
- `OWNER_APPROVED`
- `OWNER_REJECTED`

## Notes

- This monitor is observational only.
- The Daml mandate is what enforces the spending rules.
- The monitor intentionally ignores unrelated Canton contracts and token
  activity.
