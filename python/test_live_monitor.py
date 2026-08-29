from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PY_DIR = pathlib.Path(__file__).resolve().parent
if str(PY_DIR) not in sys.path:
    sys.path.insert(0, str(PY_DIR))

import live_monitor as monitor  # noqa: E402
from live_monitor import (  # noqa: E402
    _classify_close,
    ProtocolError,
    advance_cursor,
    build_updates_request,
    format_pending_payment,
    format_transaction_record,
    ledger_ws_url,
    parse_update_item,
    resolve_subscription_parties,
    stream_ws_updates,
)
from monitor_state import load_last_offset, save_last_offset  # noqa: E402


def pending_payment_update() -> dict:
    return {
        "update": {
            "Transaction": {
                "value": {
                    "updateId": "upd-101",
                    "effectiveAt": "2026-08-29T10:00:00Z",
                    "offset": "101",
                    "synchronizerId": "sync-1",
                    "recordTime": "2026-08-29T10:00:01Z",
                    "events": [
                        {
                            "CreatedEvent": {
                                "contractId": "cid-pending-1",
                                "templateId": {
                                    "packageId": "pkg-1",
                                    "moduleName": "Mandate",
                                    "entityName": "PendingPayment",
                                },
                                "createArguments": {
                                    "fields": [
                                        {"label": "owner", "value": {"party": "Alice"}},
                                        {"label": "spender", "value": {"party": "Agent"}},
                                        {"label": "recipient", "value": {"party": "Merchant"}},
                                        {"label": "amount", "value": {"decimal": "42.5"}},
                                        {"label": "purpose", "value": {"text": "books"}},
                                        {
                                            "label": "requestedAt",
                                            "value": {"timestamp": "2026-08-29T10:00:00Z"},
                                        },
                                        {"label": "status", "value": {"text": "PENDING"}},
                                    ]
                                },
                            }
                        }
                    ],
                }
            }
        }
    }


def transaction_record_update(status: str) -> dict:
    spent_after = "112.34" if status != "OWNER_REJECTED" else "100.00"
    return {
        "update": {
            "Transaction": {
                "value": {
                    "updateId": "upd-202",
                    "effectiveAt": "2026-08-29T10:00:00Z",
                    "offset": 202,
                    "synchronizerId": "sync-1",
                    "recordTime": "2026-08-29T10:00:01Z",
                    "events": [
                        {
                            "CreatedEvent": {
                                "contractId": "cid-record-1",
                                "templateId": {
                                    "packageId": "pkg-1",
                                    "moduleName": "Mandate",
                                    "entityName": "TransactionRecord",
                                },
                                "createArguments": {
                                    "owner": {"party": "Alice"},
                                    "spender": {"party": "Agent"},
                                    "recipient": {"party": "Merchant"},
                                    "amount": {"decimal": "12.34"},
                                    "purpose": {"text": "snacks"},
                                    "status": {"text": status},
                                    "spentBefore": {"decimal": "100.00"},
                                    "spentAfter": {"decimal": spent_after},
                                },
                            }
                        }
                    ],
                }
            }
        }
    }


def checkpoint_update() -> dict:
    return {
        "update": {
            "OffsetCheckpoint": {
                "value": {
                    "offset": "303",
                    "recordTime": "2026-08-29T10:05:00Z",
                }
            }
        }
    }


def error_response() -> dict:
    return {
        "code": "INVALID_ARGUMENT",
        "cause": "invalid subscription request",
        "context": {"field": "updateFormat"},
        "errorCategory": "INVALID_ARGUMENT",
        "correlationId": "corr-1",
        "traceId": "trace-1",
        "resources": [],
    }


class LiveMonitorParsingTests(unittest.TestCase):
    def test_ws_url(self) -> None:
        self.assertEqual(
            ledger_ws_url(),
            "ws://localhost:2975/v2/updates",
        )

    def test_subscription_request_shape(self) -> None:
        self.assertEqual(
            build_updates_request(123, parties=["Alice"]),
            {
                "beginExclusive": 123,
                "updateFormat": {
                    "includeTransactions": {
                        "transactionShape": "TRANSACTION_SHAPE_LEDGER_EFFECTS",
                        "eventFormat": {
                            "filtersByParty": {"Alice": {}},
                            "verbose": True,
                        },
                    }
                },
            },
        )
        self.assertEqual(
            build_updates_request(123, end_inclusive=456, parties=["Alice", "Bob"]),
            {
                "beginExclusive": 123,
                "updateFormat": {
                    "includeTransactions": {
                        "transactionShape": "TRANSACTION_SHAPE_LEDGER_EFFECTS",
                        "eventFormat": {
                            "filtersByParty": {"Alice": {}, "Bob": {}},
                            "verbose": True,
                        },
                    }
                },
                "endInclusive": 456,
            },
        )

    def test_explicit_party_selection_single(self) -> None:
        self.assertEqual(resolve_subscription_parties(["Alice::123"]), ["Alice::123"])

    def test_explicit_party_selection_multiple(self) -> None:
        self.assertEqual(
            resolve_subscription_parties(["Alice::123", "Bob::456"]),
            ["Alice::123", "Bob::456"],
        )

    def test_automatic_local_party_selection(self) -> None:
        original = monitor.c8lab.local_parties
        try:
            monitor.c8lab.local_parties = lambda: ["Alice::123", "Bob::456"]
            self.assertEqual(
                resolve_subscription_parties(None),
                ["Alice::123", "Bob::456"],
            )
        finally:
            monitor.c8lab.local_parties = original

    def test_no_party_available_fails_before_connect(self) -> None:
        original = monitor.c8lab.local_parties
        called = False

        class FakeWS:
            def send(self, payload: str) -> None:
                raise AssertionError("should not connect")

            def close(self) -> None:
                pass

        def fake_connect():
            nonlocal called
            called = True
            return FakeWS()

        try:
            monitor.c8lab.local_parties = lambda: []
            gen = stream_ws_updates(88, connect_fn=fake_connect)
            with self.assertRaisesRegex(
                ProtocolError,
                "No subscription party available",
            ):
                next(gen)
            self.assertFalse(called)
        finally:
            monitor.c8lab.local_parties = original

    def test_filters_by_party_populated_correctly(self) -> None:
        request = build_updates_request(123, parties=["Alice::123", "Bob::456"])
        filters_by_party = request["updateFormat"]["includeTransactions"]["eventFormat"]["filtersByParty"]
        self.assertEqual(list(filters_by_party.keys()), ["Alice::123", "Bob::456"])
        self.assertEqual(filters_by_party["Alice::123"], {})
        self.assertEqual(filters_by_party["Bob::456"], {})

    def test_pending_payment_created_event_parsing(self) -> None:
        parsed = parse_update_item(pending_payment_update())
        self.assertEqual(parsed.kind, "Transaction")
        self.assertEqual(parsed.offset, 101)
        self.assertEqual(len(parsed.events), 1)
        event = parsed.events[0]
        self.assertEqual(event.template_name, "PendingPayment")
        self.assertEqual(event.event_type, "PENDING_PAYMENT")
        self.assertEqual(event.contract_id, "cid-pending-1")
        self.assertIn("Agent", format_pending_payment(event))
        self.assertIn("HIGH VALUE PAYMENT REQUIRES APPROVAL", format_pending_payment(event))

    def test_transaction_record_auto_approved(self) -> None:
        parsed = parse_update_item(transaction_record_update("AUTO_APPROVED"))
        self.assertEqual(parsed.kind, "Transaction")
        event = parsed.events[0]
        self.assertEqual(event.template_name, "TransactionRecord")
        self.assertEqual(event.event_type, "AUTO_APPROVED")
        out = format_transaction_record(event)
        self.assertIn("AUTO_APPROVED", out)
        self.assertIn("100.00 -> 112.34", out)

    def test_transaction_record_owner_approved(self) -> None:
        parsed = parse_update_item(transaction_record_update("OWNER_APPROVED"))
        self.assertEqual(parsed.kind, "Transaction")
        event = parsed.events[0]
        self.assertEqual(event.event_type, "OWNER_APPROVED")
        out = format_transaction_record(event)
        self.assertIn("OWNER_APPROVED", out)

    def test_transaction_record_owner_rejected(self) -> None:
        parsed = parse_update_item(transaction_record_update("OWNER_REJECTED"))
        self.assertEqual(parsed.kind, "Transaction")
        event = parsed.events[0]
        self.assertEqual(event.event_type, "OWNER_REJECTED")
        out = format_transaction_record(event)
        self.assertIn("OWNER_REJECTED", out)
        self.assertIn("100.00 -> 100.00", out)

    def test_unrelated_contract_ignored(self) -> None:
        parsed = parse_update_item(
            {
                "update": {
                    "Transaction": {
                        "value": {
                            "offset": 303,
                            "events": [
                                {
                                    "CreatedEvent": {
                                        "contractId": "cid-other",
                                        "templateId": {
                                            "packageId": "pkg-1",
                                            "moduleName": "Other",
                                            "entityName": "Noise",
                                        },
                                        "createArguments": {"foo": {"text": "bar"}},
                                    }
                                }
                            ],
                        }
                    }
                }
            }
        )
        self.assertEqual(parsed.kind, "Transaction")
        self.assertEqual(parsed.offset, 303)
        self.assertEqual(parsed.events, [])

    def test_malformed_event_handled_safely(self) -> None:
        parsed = parse_update_item({"update": {"Transaction": {"value": {"events": [{"nope": 1}]}}}})
        self.assertEqual(parsed.kind, "Transaction")
        self.assertIsNone(parsed.offset)
        self.assertEqual(parsed.events, [])
        self.assertIsNone(parsed.warning)

    def test_error_response_envelope(self) -> None:
        parsed = parse_update_item(error_response())
        self.assertEqual(parsed.kind, "error")
        self.assertIsNone(parsed.offset)
        self.assertIsNotNone(parsed.error)
        self.assertIn("INVALID_ARGUMENT", parsed.warning or "")

    def test_protocol_close_classification(self) -> None:
        self.assertEqual(_classify_close(1008, "invalid subscription request"), "protocol")
        self.assertEqual(_classify_close(1006, "connection lost"), "transient")

    def test_websocket_subscription_request_sent(self) -> None:
        class FakeWS:
            def __init__(self) -> None:
                self.sent = []
                self.closed = False
                self.close_status_code = None
                self.close_reason = None
                self.messages = [
                    json.dumps(pending_payment_update()),
                ]

            def send(self, payload: str) -> None:
                self.sent.append(payload)

            def recv(self):
                if self.messages:
                    return self.messages.pop(0)
                self.close_status_code = 1000
                self.close_reason = "normal closure"
                return None

            def close(self) -> None:
                self.closed = True

        fake_ws = FakeWS()

        def fake_connect():
            return fake_ws

        gen = stream_ws_updates(88, connect_fn=fake_connect, parties=["Alice"])
        first = next(gen)
        self.assertEqual(first, pending_payment_update())
        self.assertEqual(
            json.loads(fake_ws.sent[0]),
            {
                "beginExclusive": 88,
                "updateFormat": {
                    "includeTransactions": {
                        "transactionShape": "TRANSACTION_SHAPE_LEDGER_EFFECTS",
                        "eventFormat": {
                            "filtersByParty": {"Alice": {}},
                            "verbose": True,
                        },
                    }
                },
            },
        )
        gen.close()
        self.assertTrue(fake_ws.closed)


class StateFileTests(unittest.TestCase):
    def test_state_file_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "monitor_state.json"
            self.assertIsNone(load_last_offset(path))
            save_last_offset(path, "12345")
            self.assertEqual(load_last_offset(path), "12345")

    def test_resume_prefers_saved_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "monitor_state.json"
            save_last_offset(path, "42")
            self.assertEqual(load_last_offset(path), "42")

    def test_cursor_advances_for_unrelated_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "monitor_state.json"
            parsed = parse_update_item(
                {
                    "update": {
                        "Transaction": {
                            "value": {
                                "offset": 303,
                                "events": [
                                    {
                                        "CreatedEvent": {
                                            "contractId": "cid-other",
                                            "templateId": {
                                                "packageId": "pkg-1",
                                                "moduleName": "Other",
                                                "entityName": "Noise",
                                            },
                                            "createArguments": {"foo": {"text": "bar"}},
                                        }
                                    }
                                ],
                            }
                        }
                    }
                }
            )
            cursor = advance_cursor(100, parsed, path)
            self.assertEqual(cursor, 303)
            self.assertEqual(load_last_offset(path), "303")

    def test_checkpoint_is_parsed(self) -> None:
        parsed = parse_update_item(checkpoint_update())
        self.assertEqual(parsed.kind, "OffsetCheckpoint")
        self.assertTrue(parsed.checkpoint)
        self.assertEqual(parsed.offset, 303)


if __name__ == "__main__":
    unittest.main()
