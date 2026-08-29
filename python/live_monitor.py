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
from typing import Any, Iterable, Optional, Sequence


ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import c8lab  # noqa: E402
from monitor_state import load_last_offset, save_last_offset  # noqa: E402


DEFAULT_STATE_FILE = pathlib.Path(__file__).with_name("monitor_state.json")
DEFAULT_RECONNECT_DELAY_SECONDS = 2.0
DEFAULT_DEBUG_MAX_FRAMES = 8
DEFAULT_DEBUG_MAX_FRAME_CHARS = 3000
TRANSACTION_SHAPE = "TRANSACTION_SHAPE_LEDGER_EFFECTS"


class ProtocolError(c8lab.LabError):
    """The server returned a protocol or subscription error."""


class TransientConnectionError(c8lab.LabError):
    """The websocket dropped or ended without a protocol error."""


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

    kind: str
    offset: Optional[int]
    events: list[ParsedContractEvent] = field(default_factory=list)
    checkpoint: bool = False
    warning: Optional[str] = None
    error: Optional[dict[str, Any]] = None


@dataclass
class ProtocolDebug:
    enabled: bool = False
    max_frames: int = DEFAULT_DEBUG_MAX_FRAMES
    max_frame_chars: int = DEFAULT_DEBUG_MAX_FRAME_CHARS
    frame_count: int = 0
    subscription_sent: bool = False


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

    primitive_keys = (
        "text",
        "party",
        "decimal",
        "timestamp",
        "date",
        "int64",
        "bool",
        "unit",
        "contractId",
        "contract_id",
        "id",
        "value",
        "string",
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
    if value is None or isinstance(value, bool):
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
        for key in ("offsetCheckpoint", "OffsetCheckpoint", "checkpoint", "value"):
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


def _looks_like_canton_error(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    required = {"code", "cause", "context", "errorCategory"}
    return required.issubset(node.keys())


def _unwrap_variant(node: Any) -> tuple[str, Any]:
    if not isinstance(node, dict):
        return "", node
    for key in ("Transaction", "transaction"):
        if key in node:
            return "Transaction", node[key]
    for key in ("OffsetCheckpoint", "offsetCheckpoint"):
        if key in node:
            return "OffsetCheckpoint", node[key]
    for key in ("Reassignment", "reassignment"):
        if key in node:
            return "Reassignment", node[key]
    for key in ("TopologyTransaction", "topologyTransaction"):
        if key in node:
            return "TopologyTransaction", node[key]
    return "", node


def _unwrap_variant_value(node: Any) -> Any:
    if isinstance(node, dict):
        if "value" in node and len(node) == 1:
            return node["value"]
        if "value" in node:
            return node["value"]
    return node


def _extract_created_event(node: Any) -> Optional[dict[str, Any]]:
    if not isinstance(node, dict):
        return None
    for key in ("createdEvent", "CreatedEvent", "created_event"):
        if key in node:
            created = _unwrap_variant_value(node[key])
            if isinstance(created, dict):
                return created
            return None
    if any(key in node for key in ("contractId", "contract_id")) and any(
        key in node for key in ("templateId", "template_id")
    ):
        return node
    if "value" in node and len(node) == 1:
        return _extract_created_event(node["value"])
    return None


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


def _parse_transaction(transaction: dict[str, Any], kind: str) -> ParsedUpdate:
    offset = _extract_offset(transaction)
    events: list[ParsedContractEvent] = []

    raw_events = transaction.get("events")
    if isinstance(raw_events, list):
        for raw_event in raw_events:
            created_event = _extract_created_event(raw_event)
            if created_event is None:
                continue
            parsed = _parse_event(created_event, offset)
            if parsed is not None:
                events.append(parsed)
    elif raw_events is not None:
        return ParsedUpdate(kind="malformed", offset=offset, warning="transaction events field is not a list")

    return ParsedUpdate(kind=kind, offset=offset, events=events)


def _parse_canton_error(node: dict[str, Any]) -> ParsedUpdate:
    error = {
        "code": str(node.get("code", "")),
        "cause": str(node.get("cause", "")),
        "context": node.get("context", {}),
        "errorCategory": node.get("errorCategory"),
        "correlationId": node.get("correlationId"),
        "traceId": node.get("traceId"),
        "resources": node.get("resources", []),
        "grpcCodeValue": node.get("grpcCodeValue"),
        "retryInfo": node.get("retryInfo"),
    }
    return ParsedUpdate(
        kind="error",
        offset=None,
        warning=f"{error['code']}: {error['cause']}",
        error=error,
    )


def parse_update_item(item: Any) -> ParsedUpdate:
    """Parse one raw update envelope into printable contract events."""
    if _looks_like_canton_error(item):
        return _parse_canton_error(item)

    envelope = _unwrap_update_envelope(item)
    if _looks_like_canton_error(envelope):
        return _parse_canton_error(envelope)

    if not isinstance(envelope, dict):
        return ParsedUpdate(kind="malformed", offset=None, warning="unexpected update shape")

    variant, payload = _unwrap_variant(envelope)
    if not variant:
        if any(key in envelope for key in ("events", "event", "createdEvent", "CreatedEvent")):
            return _parse_transaction(envelope, "Transaction")
        if any(key in envelope for key in ("offset", "ledgerOffset", "offsetCheckpoint")):
            return ParsedUpdate(
                kind="OffsetCheckpoint",
                offset=_extract_offset(envelope),
                checkpoint=True,
            )
        return ParsedUpdate(kind="unsupported", offset=_extract_offset(envelope), warning="unsupported update variant")

    payload = _unwrap_variant_value(payload)
    if variant == "Transaction":
        if not isinstance(payload, dict):
            return ParsedUpdate(kind="malformed", offset=_extract_offset(envelope), warning="transaction payload is not an object")
        return _parse_transaction(payload, "Transaction")

    if variant == "OffsetCheckpoint":
        return ParsedUpdate(
            kind="OffsetCheckpoint",
            offset=_extract_offset(payload),
            checkpoint=True,
        )

    if variant == "Reassignment":
        return ParsedUpdate(kind="Reassignment", offset=_extract_offset(payload))

    if variant == "TopologyTransaction":
        return ParsedUpdate(kind="TopologyTransaction", offset=_extract_offset(payload))

    return ParsedUpdate(kind="unsupported", offset=_extract_offset(envelope), warning="unsupported update variant")


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


def advance_cursor(cursor: int, parsed: ParsedUpdate, state_file: pathlib.Path) -> int:
    if parsed.offset is not None and parsed.kind != "error":
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
        "Status:      PENDING",
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
    return _coerce_int(c8lab.ledger_end())


def ledger_ws_url() -> str:
    base = c8lab.BASE.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):] + "/v2/updates"
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):] + "/v2/updates"
    return base + "/v2/updates"


def _normalize_parties(parties: Sequence[str]) -> list[str]:
    return [str(party) for party in parties]


def resolve_subscription_parties(explicit_parties: Optional[Sequence[str]] = None) -> list[str]:
    if explicit_parties is not None:
        parties = _normalize_parties(explicit_parties)
    else:
        try:
            parties = _normalize_parties(c8lab.local_parties())
        except c8lab.LabError:
            parties = []
    parties = [party for party in parties if party.strip()]
    if not parties:
        raise ProtocolError(
            "No subscription party available. Pass --party <FULL_PARTY_ID> or retry party discovery."
        )
    return parties


def build_update_format(parties: Sequence[str]) -> dict[str, Any]:
    active_parties = _normalize_parties(parties)
    if not active_parties:
        raise ProtocolError(
            "No subscription party available. Pass --party <FULL_PARTY_ID> or retry party discovery."
        )
    event_format: dict[str, Any] = {
        "verbose": True,
        "filtersByParty": {party: {} for party in active_parties},
    }
    return {
        "includeTransactions": {
            "transactionShape": TRANSACTION_SHAPE,
            "eventFormat": event_format,
        }
    }


def build_updates_request(
    begin_exclusive: int,
    end_inclusive: Optional[int] = None,
    parties: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    resolved_parties = resolve_subscription_parties(parties)
    request: dict[str, Any] = {
        "beginExclusive": begin_exclusive,
        "updateFormat": build_update_format(parties=resolved_parties),
    }
    if end_inclusive is not None:
        request["endInclusive"] = end_inclusive
    return request


def subscription_json(begin_exclusive: int,
                      end_inclusive: Optional[int] = None,
                      parties: Optional[Sequence[str]] = None) -> str:
    return json.dumps(
        build_updates_request(
            begin_exclusive,
            end_inclusive=end_inclusive,
            parties=parties,
        ),
        separators=(",", ":"),
        sort_keys=True,
    )


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


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"...<truncated {len(value) - limit} chars>"


def _debug_print(debug: Optional[ProtocolDebug], message: str) -> None:
    if debug and debug.enabled:
        print(message, file=sys.stderr)


def _debug_print_subscription(debug: Optional[ProtocolDebug], request: dict[str, Any]) -> None:
    if not debug or not debug.enabled or debug.subscription_sent:
        return
    debug.subscription_sent = True
    _debug_print(debug, "subscription JSON:")
    _debug_print(debug, json.dumps(request, indent=2, sort_keys=True))


def _debug_print_frame(debug: Optional[ProtocolDebug], raw_text: str) -> None:
    if not debug or not debug.enabled:
        return
    if debug.frame_count >= debug.max_frames:
        if debug.frame_count == debug.max_frames:
            _debug_print(debug, f"raw frame logging suppressed after {debug.max_frames} frames")
        debug.frame_count += 1
        return
    debug.frame_count += 1
    _debug_print(debug, f"raw frame #{debug.frame_count}:")
    _debug_print(debug, _truncate_text(raw_text, debug.max_frame_chars))


def _debug_print_close(ws: Any, debug: Optional[ProtocolDebug]) -> None:
    if not debug or not debug.enabled:
        return
    code = getattr(ws, "close_status_code", None)
    reason = getattr(ws, "close_reason", None)
    _debug_print(debug, f"websocket close code: {code!r}")
    _debug_print(debug, f"websocket close reason: {reason!r}")


def _debug_exception(exc: BaseException, debug: Optional[ProtocolDebug]) -> None:
    if not debug or not debug.enabled:
        return
    _debug_print(debug, f"exception type: {type(exc).__name__}")
    _debug_print(debug, f"exception message: {exc}")


def _is_protocol_close_reason(reason: Any) -> bool:
    if not isinstance(reason, str):
        return False
    text = reason.lower()
    return any(
        token in text
        for token in (
            "invalid",
            "schema",
            "subscription",
            "unsupported",
            "updateformat",
            "beginexclusive",
            "bad request",
            "protocol",
            "decode",
        )
    )


def _classify_close(code: Any, reason: Any) -> str:
    if _is_protocol_close_reason(reason):
        return "protocol"
    if code in {1002, 1003, 1007, 1008, 1009, 1011}:
        return "protocol"
    return "transient"


def _recv_ws_message(ws: Any, debug: Optional[ProtocolDebug]) -> Any:
    try:
        raw = ws.recv()
    except Exception as exc:
        _debug_exception(exc, debug)
        code = getattr(ws, "close_status_code", None)
        reason = getattr(ws, "close_reason", None)
        if _classify_close(code, reason) == "protocol":
            raise ProtocolError(
                f"websocket closed with protocol error: code={code!r} reason={reason!r}"
            ) from exc
        raise TransientConnectionError(
            f"websocket connection dropped: code={code!r} reason={reason!r}"
        ) from exc

    if raw is None:
        code = getattr(ws, "close_status_code", None)
        reason = getattr(ws, "close_reason", None)
        if _classify_close(code, reason) == "protocol":
            raise ProtocolError(
                f"websocket closed with protocol error: code={code!r} reason={reason!r}"
            )
        raise TransientConnectionError(
            f"websocket connection closed: code={code!r} reason={reason!r}"
        )

    if isinstance(raw, bytes):
        raw_text = raw.decode("utf-8", errors="replace")
    else:
        raw_text = str(raw)

    _debug_print_frame(debug, raw_text)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(
            f"server sent a non-JSON frame: {_truncate_text(raw_text, 200)}"
        ) from exc


def stream_ws_updates(
    begin_exclusive: int,
    end_inclusive: Optional[int] = None,
    connect_fn=_open_ws_connection,
    debug: Optional[ProtocolDebug] = None,
    parties: Optional[Sequence[str]] = None,
):
    request = build_updates_request(
        begin_exclusive,
        end_inclusive=end_inclusive,
        parties=parties,
    )
    ws = connect_fn()
    try:
        _debug_print_subscription(debug, request)
        ws.send(json.dumps(request, separators=(",", ":"), sort_keys=True))
        while True:
            yield _recv_ws_message(ws, debug)
    finally:
        _debug_print_close(ws, debug)
        try:
            ws.close()
        except Exception:
            pass


def _format_protocol_error(parsed: ParsedUpdate) -> str:
    if parsed.error:
        code = parsed.error.get("code", "ERROR")
        cause = parsed.error.get("cause", "")
        return f"{code}: {cause}"
    if parsed.warning:
        return parsed.warning
    return "protocol error"


def run_monitor(
    state_file: pathlib.Path,
    from_now: bool,
    reconnect_delay_seconds: float,
    subscription_parties: Sequence[str],
    debug_protocol: bool = False,
) -> None:
    cursor = _load_or_init_offset(state_file, from_now)
    debug = ProtocolDebug(enabled=debug_protocol)

    print(f"WebSocket URL: {ledger_ws_url()}")
    print(f"Starting from offset: {cursor}")
    print(f"State file: {state_file}")
    if debug_protocol:
        print("Subscription parties:")
        for party in subscription_parties:
            print(f"- {party}")

    while True:
        try:
            for raw in stream_ws_updates(
                cursor,
                connect_fn=_open_ws_connection,
                debug=debug,
                parties=subscription_parties,
            ):
                parsed = parse_update_item(raw)
                if parsed.kind in {"error", "malformed", "unsupported"}:
                    raise ProtocolError(_format_protocol_error(parsed))
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
        except ProtocolError as exc:
            print(f"protocol error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        except c8lab.LabError as exc:
            message = str(exc)
            print(f"monitor error: {message}", file=sys.stderr)
            if "401" in message or "403" in message or "C8_CLIENT_SECRET" in message:
                raise SystemExit(1)
            time.sleep(max(reconnect_delay_seconds, 2.0))
        except Exception as exc:  # pragma: no cover - defensive
            _debug_exception(exc, debug)
            print(
                f"unexpected monitor failure: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
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
    parser.add_argument(
        "--party",
        action="append",
        dest="parties",
        metavar="FULL_PARTY_ID",
        help="full Canton party ID to subscribe as (repeatable)",
    )
    parser.add_argument(
        "--debug-protocol",
        action="store_true",
        help="print websocket subscription, raw frames, close status, and exceptions",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    subscription_parties = resolve_subscription_parties(args.parties)
    run_monitor(
        state_file=pathlib.Path(args.state_file),
        from_now=args.from_now,
        reconnect_delay_seconds=args.reconnect_seconds,
        subscription_parties=subscription_parties,
        debug_protocol=args.debug_protocol,
    )


if __name__ == "__main__":
    main()
