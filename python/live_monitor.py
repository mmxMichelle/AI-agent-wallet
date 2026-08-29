#!/usr/bin/env python3
"""Live Canton Ledger monitor for Mandate contract activity.

This follows the ledger WebSocket update feed, filters for
Mandate.PendingPayment and Mandate.TransactionRecord creations, and prints
human-readable terminal alerts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import c8lab  # noqa: E402
from monitor_state import load_last_offset, save_last_offset  # noqa: E402


DEFAULT_STATE_FILE = pathlib.Path(__file__).with_name("monitor_state.json")
DEFAULT_RECONNECT_DELAY_SECONDS = 2.0


@dataclass(frozen=True)
class ParsedContractEvent:
    """A single printable contract creation event."""

    event_type: str
    template_name: str
    contract_id: str
    fields: dict[str, Any] = field(default_factory=dict)
    offset: Optional[int] = None


@dataclass(frozen=True)
class ParsedUpdate:
    """Normalized view of one ledger update envelope."""

    offset: Optional[int]
    events: list[ParsedContractEvent] = field(default_factory=list)
    checkpoint: bool = False
    warning: Optional[str] = None


def _first_present(data: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _unwrap_scalar(value: Any) -> Any:
    if isinstance(value, list):
        return [_unwrap_scalar(v) for v in value]
    if not isinstance(value, dict):
        return value

    if "fields" in value and isinstance(value["fields"], list):
        return {
            str(item.get("label", "")): _unwrap_scalar(item.get("value"))
            for item in value["fields"]
            if isinstance(item, dict) and item.get("label") is not None
        }

    # Ledger JSON uses one-key wrappers for many primitive values.
    primitive_keys = (
        "text", "party", "decimal", "timestamp", "date", "int64", "bool",
        "unit", "contractId", "contract_id", "id", "value", "string",
    )
    for key in primitive_keys:
        if key in value:
            return _unwrap_scalar(value[key])

    if "record" in value:
        return _unwrap_scalar(value["record"])
    if "optional" in value:
        return _unwrap_scalar(value["optional"])
    if "list" in value:
        return _unwrap_scalar(value["list"])
    if "map" in value:
        return {
            str(_unwrap_scalar(entry.get("key"))): _unwrap_scalar(entry.get("value"))
            for entry in value["map"]
            if isinstance(entry, dict)
        }

    # Already a useful object.
    return {k: _unwrap_scalar(v) for k, v in value.items()}


def _normalize_template_id(template_id: Any) -> tuple[str, str, str]:
    if isinstance(template_id, str):
        return "", "", template_id
    if not isinstance(template_id, dict):
        return "", "", str(template_id)
    package_id = str(_first_present(template_id, ("packageId", "package_id")) or "")
    module_name = str(_first_present(template_id, ("moduleName", "module_name")) or "")
    entity_name = str(_first_present(template_id, ("entityName", "entity_name")) or "")
    return package_id, module_name, entity_name


def _coerce_offset(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        for key in ("offset", "ledgerOffset", "ledger_offset", "absoluteOffset"):
            if key in value:
                return _coerce_offset(value[key])
    return None


def _extract_offset(node: Any) -> Optional[int]:
    if isinstance(node, dict):
        for key in ("offset", "ledgerOffset", "ledger_offset"):
            if key in node:
                offset = _coerce_offset(node[key])
                if offset is not None:
                    return offset
        for key in ("offsetCheckpoint", "OffsetCheckpoint"):
            if key in node:
                offset = _extract_offset(node[key])
                if offset is not None:
                    return offset
        for value in node.values():
            offset = _extract_offset(value)
            if offset is not None:
                return offset
    elif isinstance(node, list):
        for value in node:
            offset = _extract_offset(value)
            if offset is not None:
                return offset
    return None


def _unwrap_update_envelope(item: Any) -> Any:
    if isinstance(item, dict) and "update" in item and len(item) == 1:
        return item["update"]
    return item


def _walk_created_event_dicts(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, list):
        for entry in node:
            yield from _walk_created_event_dicts(entry)
        return
    if not isinstance(node, dict):
        return

    if any(key in node for key in ("templateId", "template_id")) and any(
        key in node for key in ("contractId", "contract_id")
    ):
        yield node

    for value in node.values():
        yield from _walk_created_event_dicts(value)


def _extract_created_arguments(created_event: dict[str, Any]) -> dict[str, Any]:
    raw_args = _first_present(
        created_event,
        ("createArguments", "create_arguments", "arguments", "argument", "value"),
    )
    if raw_args is None:
        return {}
    normalized = _unwrap_scalar(raw_args)
    return normalized if isinstance(normalized, dict) else {"value": normalized}


def _template_name(created_event: dict[str, Any]) -> str:
    template_id = _first_present(created_event, ("templateId", "template_id"))
    _package_id, module_name, entity_name = _normalize_template_id(template_id)
    if module_name == "Mandate" and entity_name in {"PendingPayment", "TransactionRecord"}:
        return entity_name
    if entity_name in {"PendingPayment", "TransactionRecord"}:
        return entity_name
    return ""


def _parse_event(event: dict[str, Any], offset: Optional[int]) -> Optional[ParsedContractEvent]:
    template_name = _template_name(event)
    if not template_name:
        return None
    contract_id = str(_first_present(event, ("contractId", "contract_id")) or "")
    fields = _extract_created_arguments(event)
    status = str(fields.get("status", "")) if template_name == "TransactionRecord" else ""
    event_type = status or ("PENDING_PAYMENT" if template_name == "PendingPayment" else template_name)
    return ParsedContractEvent(
        event_type=event_type,
        template_name=template_name,
        contract_id=contract_id,
        fields=fields,
        offset=offset,
    )


def parse_update_item(item: Any) -> ParsedUpdate:
    """Parse one raw update envelope into printable contract events."""
    envelope = _unwrap_update_envelope(item)
    offset = _extract_offset(envelope)

    if not isinstance(envelope, dict):
        return ParsedUpdate(offset=offset, warning="unexpected update shape")

    # Offset checkpoints are heartbeats. They matter for resuming, but they do
    # not produce terminal output.
    if any(key in envelope for key in ("offsetCheckpoint", "OffsetCheckpoint")):
        return ParsedUpdate(offset=offset, checkpoint=True)

    events: list[ParsedContractEvent] = []
    for created_event in _walk_created_event_dicts(envelope):
        parsed = _parse_event(created_event, offset)
        if parsed is not None:
            events.append(parsed)

    if not events and offset is None:
        return ParsedUpdate(offset=None, warning="malformed or unsupported update")
    return ParsedUpdate(offset=offset, events=events)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "party", "decimal", "timestamp", "date", "int64", "value"):
            if key in value:
                return _text(value[key])
        return json.dumps(value, sort_keys=True)
    if isinstance(value, list):
        return json.dumps([_unwrap_scalar(v) for v in value], sort_keys=True)
    return str(value)


def _fmt_field(fields: dict[str, Any], name: str) -> str:
    return _text(fields.get(name))


def advance_cursor(cursor: int, parsed: ParsedUpdate,
                   state_file: pathlib.Path) -> int:
    if parsed.offset is not None:
        cursor = max(cursor, parsed.offset)
        save_last_offset(state_file, cursor)
    return cursor


def format_pending_payment(event: ParsedContractEvent) -> str:
    fields = event.fields
    lines = [
        "-" * 50,
        "HIGH VALUE PAYMENT REQUIRES APPROVAL",
        "-" * 50,
        f"Agent:       {_fmt_field(fields, 'spender')}",
        f"Recipient:   {_fmt_field(fields, 'recipient')}",
        f"Amount:      {_fmt_field(fields, 'amount')}",
        f"Purpose:     {_fmt_field(fields, 'purpose')}",
        f"Requested:   {_fmt_field(fields, 'requestedAt')}",
        f"Status:      PENDING",
        f"Contract ID: {event.contract_id}",
        "-" * 50,
    ]
    return "\n".join(lines)


def format_transaction_record(event: ParsedContractEvent) -> str:
    fields = event.fields
    timestamp = dt.datetime.now().strftime("%H:%M:%S")
    status = _text(fields.get("status")) or event.event_type
    lines = [
        f"[{timestamp}] {status}",
        f"Agent:       {_fmt_field(fields, 'spender')}",
        f"Recipient:   {_fmt_field(fields, 'recipient')}",
        f"Amount:      {_fmt_field(fields, 'amount')}",
        f"Purpose:     {_fmt_field(fields, 'purpose')}",
        f"Spent:       {_fmt_field(fields, 'spentBefore')} -> {_fmt_field(fields, 'spentAfter')}",
    ]
    return "\n".join(lines)


def render_event(event: ParsedContractEvent) -> str:
    if event.template_name == "PendingPayment":
        return format_pending_payment(event)
    if event.template_name == "TransactionRecord":
        return format_transaction_record(event)
    return f"unhandled event: {event}"


def _coerce_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise ValueError(f"cannot coerce {value!r} to int")


def _load_or_init_offset(state_file: pathlib.Path, from_now: bool) -> int:
    if not from_now:
        saved = load_last_offset(state_file)
        if saved is not None:
            return _coerce_int(saved)
    return c8lab.ledger_end()


def ledger_ws_url() -> str:
    base = c8lab.BASE.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):] + "/v2/updates"
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):] + "/v2/updates"
    return base + "/v2/updates"


def build_updates_request(begin_exclusive: int, end_inclusive: Optional[int] = None,
                          verbose: bool = True) -> dict[str, Any]:
    request: dict[str, Any] = {
        "beginExclusive": begin_exclusive,
        "verbose": verbose,
    }
    if end_inclusive is not None:
        request["endInclusive"] = end_inclusive
    return request


def websocket_headers() -> list[str]:
    return [f"Authorization: Bearer {c8lab.token()}"]


def _open_ws_connection():
    try:
        import websocket  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency issue
        raise c8lab.LabError(
            "websocket-client is required. Install python/requirements.txt."
        ) from exc
    return websocket.create_connection(
        ledger_ws_url(),
        header=websocket_headers(),
        timeout=30,
    )


def _recv_ws_message(ws: Any) -> Any:
    raw = ws.recv()
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def stream_ws_updates(begin_exclusive: int, end_inclusive: Optional[int] = None,
                      connect_fn=_open_ws_connection):
    ws = connect_fn()
    try:
        request = build_updates_request(begin_exclusive, end_inclusive=end_inclusive)
        ws.send(json.dumps(request))
        while True:
            yield _recv_ws_message(ws)
    finally:
        try:
            ws.close()
        except Exception:
            pass


def run_monitor(state_file: pathlib.Path, from_now: bool,
                reconnect_delay_seconds: float) -> None:
    cursor = _load_or_init_offset(state_file, from_now)
    print(f"WebSocket URL: {ledger_ws_url()}")
    print(f"Starting from offset: {cursor}")
    print(f"State file: {state_file}")

    while True:
        try:
            for raw in stream_ws_updates(cursor):
                parsed = parse_update_item(raw)
                if parsed.warning:
                    print(f"warning: {parsed.warning}", file=sys.stderr)
                    continue
                cursor = advance_cursor(cursor, parsed, state_file)
                if parsed.checkpoint:
                    continue
                for event in parsed.events:
                    print(render_event(event))
                    if event.offset is not None:
                        cursor = max(cursor, event.offset)
                        save_last_offset(state_file, cursor)
        except KeyboardInterrupt:
            print("\nmonitor stopped")
            return
        except c8lab.LabError as exc:
            message = str(exc)
            print(f"monitor error: {message}", file=sys.stderr)
            if "401" in message or "403" in message or "C8_CLIENT_SECRET" in message:
                raise SystemExit(1)
            time.sleep(max(reconnect_delay_seconds, 2.0))
        except Exception as exc:  # pragma: no cover - defensive
            print(f"unexpected monitor failure: {exc}", file=sys.stderr)
            time.sleep(max(reconnect_delay_seconds, 2.0))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor Mandate contract activity")
    parser.add_argument(
        "--from-now",
        action="store_true",
        help="ignore saved state and start from the current ledger end",
    )
    parser.add_argument(
        "--state-file",
        default=str(DEFAULT_STATE_FILE),
        help="checkpoint file path (default: python/monitor_state.json)",
    )
    parser.add_argument(
        "--reconnect-seconds",
        type=float,
        default=DEFAULT_RECONNECT_DELAY_SECONDS,
        help="delay before reconnecting after a socket failure",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run_monitor(
        state_file=pathlib.Path(args.state_file),
        from_now=args.from_now,
        reconnect_delay_seconds=args.reconnect_seconds,
    )


if __name__ == "__main__":
    main()
