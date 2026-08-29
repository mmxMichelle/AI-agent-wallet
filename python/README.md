# Python Live Monitor

This monitor watches the Canton Ledger API for new `Mandate.PendingPayment`
and `Mandate.TransactionRecord` contract creations and prints them to the
terminal in real time.

## What it does

It follows the WebSocket ledger update stream, filters for the mandate
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

Install the WebSocket dependency:

```bash
python3 -m pip install -r python/requirements.txt
```

## Run

```bash
python3 python/live_monitor.py
```

Mandate client:

```bash
python3 python/mandate_client.py parties
python3 python/mandate_client.py packages
python3 python/mandate_client.py upload-dar --dar daml-starter/.daml/dist/daml-starter-0.0.1.dar
python3 python/mandate_client.py create-proposal --owner <OWNER> --spender <SPENDER> --allowed-recipient <RECIPIENT> --cap 1000 --approval-threshold 200 --expires-at 2026-08-30T00:00:00Z
python3 python/mandate_client.py settle --from-party <SPENDER> --to-party <RECIPIENT> --amount 350
```

Useful options:

```bash
python3 python/live_monitor.py --from-now
python3 python/live_monitor.py --reconnect-seconds 1.5
python3 python/live_monitor.py --state-file python/monitor_state.json
python3 python/live_monitor.py --party Alice::123 --party Bob::456
python3 python/live_monitor.py --debug-protocol
```

## Resume and checkpointing

The monitor stores the last processed ledger offset in
`python/monitor_state.json`.

On startup it:

1. Loads the saved offset if present.
2. Falls back to the current ledger end if no checkpoint exists, unless
   `--from-now` is set.
3. Connects to the WebSocket stream at `wss://<ledger-host>/v2/updates`.
4. Updates the checkpoint only after a ledger update has been processed.

The checkpoint file is written atomically.

The WebSocket subscription message is the Canton Ledger API `GetUpdatesRequest`
shape. This monitor sends:

```json
{
  "beginExclusive": 123,
  "updateFormat": {
    "includeTransactions": {
      "transactionShape": "TRANSACTION_SHAPE_LEDGER_EFFECTS",
      "eventFormat": {
        "filtersByParty": {
          "Alice": {}
        },
        "verbose": true
      }
    }
  }
}
```

`endInclusive` is only added if a bounded read is requested.

`--debug-protocol` prints the exact subscription JSON, raw incoming WebSocket
frames, close status code and reason, and exception type/message. Large frames
are truncated so the terminal does not flood.

If the monitor cannot determine a usable subscription party, it exits with a
clear error instead of sending an empty `filtersByParty` map.

The Mandate client uses the existing Ledger API command flow from `c8lab.py`
and the documented DAR upload endpoint `POST /v2/packages`. If package upload is
not permitted on the shared DevNet participant, an organizer/admin must upload
`daml-starter/.daml/dist/daml-starter-0.0.1.dar` or grant the required admin
rights.

## Contract meaning

- `PendingPayment` means a high-value charge has been requested and still
  needs owner approval.
- `TransactionRecord` is the audit trail for a processed charge, approval, or
  rejection.

Intended demo flow:

`RequestHighValue` -> `PendingPayment` -> owner `Approve` -> `TransactionRecord`
with `OWNER_APPROVED` -> Python `settle` -> `c8lab.transfer(...)` -> real Canton
Coin movement.

Current statuses:

- `AUTO_APPROVED`
- `OWNER_APPROVED`
- `OWNER_REJECTED`

## Notes

- This monitor is observational only.
- The Daml mandate is what enforces the spending rules.
- The monitor intentionally ignores unrelated Canton contracts and token
  activity.
