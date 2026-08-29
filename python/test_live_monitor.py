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

from live_monitor import (  # noqa: E402
    build_updates_request,
    advance_cursor,
    format_pending_payment,
    format_transaction_record,
    ledger_ws_url,
    _load_or_init_offset,
    parse_update_item,
    stream_ws_updates,
)
from monitor_state import load_last_offset, save_last_offset  # noqa: E402


def pending_payment_update() -> dict:
    return {
        "update": {
            "transaction": {
                "offset": "101",
                "events": [
                    {
                        "createdEvent": {
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
                                    {"label": "requestedAt", "value": {"timestamp": "2026-08-29T10:00:00Z"}},
                                    {"label": "status", "value": {"text": "PENDING"}},
                                ]
                            },
                        }
                    }
                ],
            }
        }
    }


def transaction_record_update(status: str) -> dict:
    return {
        "update": {
            "transaction": {
                "offset": 202,
                "events": [
                    {
                        "CreatedEvent": {
                            "contract_id": "cid-record-1",
                            "template_id": {
                                "package_id": "pkg-1",
                                "module_name": "Mandate",
                                "entity_name": "TransactionRecord",
                            },
                            "create_arguments": {
                                "owner": {"party": "Alice"},
                                "spender": {"party": "Agent"},
                                "recipient": {"party": "Merchant"},
                                "amount": {"decimal": "12.34"},
                                "purpose": {"text": "snacks"},
                                "status": {"text": status},
                                "spentBefore": {"decimal": "100.00"},
                                "spentAfter": {"decimal": "112.34" if status != "OWNER_REJECTED" else "100.00"},
                            },
                        }
                    }
                ],
            }
        }
    }


class LiveMonitorParsingTests(unittest.TestCase):
    def test_ws_url(self) -> None:
        self.assertEqual(
            ledger_ws_url(),
            "ws://localhost:2975/v2/updates",
        )

    def test_subscription_request_shape(self) -> None:
        self.assertEqual(
            build_updates_request(123),
            {"beginExclusive": 123, "verbose": True},
        )
        self.assertEqual(
            build_updates_request(123, end_inclusive=456),
            {"beginExclusive": 123, "verbose": True, "endInclusive": 456},
        )

    def test_pending_payment_created_event_parsing(self) -> None:
        parsed = parse_update_item(pending_payment_update())
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
        event = parsed.events[0]
        self.assertEqual(event.template_name, "TransactionRecord")
        self.assertEqual(event.event_type, "AUTO_APPROVED")
        out = format_transaction_record(event)
        self.assertIn("AUTO_APPROVED", out)
        self.assertIn("100.00 -> 112.34", out)

    def test_transaction_record_owner_approved(self) -> None:
        parsed = parse_update_item(transaction_record_update("OWNER_APPROVED"))
        event = parsed.events[0]
        self.assertEqual(event.event_type, "OWNER_APPROVED")
        out = format_transaction_record(event)
        self.assertIn("OWNER_APPROVED", out)

    def test_transaction_record_owner_rejected(self) -> None:
        parsed = parse_update_item(transaction_record_update("OWNER_REJECTED"))
        event = parsed.events[0]
        self.assertEqual(event.event_type, "OWNER_REJECTED")
        out = format_transaction_record(event)
        self.assertIn("OWNER_REJECTED", out)
        self.assertIn("100.00 -> 100.00", out)

    def test_unrelated_contract_ignored(self) -> None:
        parsed = parse_update_item({
            "update": {
                "transaction": {
                    "offset": 303,
                    "events": [
                        {
                            "createdEvent": {
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
        })
        self.assertEqual(parsed.offset, 303)
        self.assertEqual(parsed.events, [])

    def test_malformed_event_handled_safely(self) -> None:
        parsed = parse_update_item({"update": {"transaction": {"events": [{"nope": 1}]}}})
        self.assertIsNone(parsed.offset)
        self.assertEqual(parsed.events, [])
        self.assertIsNotNone(parsed.warning)

    def test_websocket_subscription_request_sent(self) -> None:
        class FakeWS:
            def __init__(self) -> None:
                self.sent = []
                self.closed = False
                self.messages = [
                    json.dumps(pending_payment_update()),
                ]

            def send(self, payload: str) -> None:
                self.sent.append(payload)

            def recv(self):
                if self.messages:
                    return self.messages.pop(0)
                raise StopIteration

            def close(self) -> None:
                self.closed = True

        fake_ws = FakeWS()

        def fake_connect():
            return fake_ws

        gen = stream_ws_updates(88, connect_fn=fake_connect)
        first = next(gen)
        self.assertEqual(first, pending_payment_update())
        self.assertEqual(
            json.loads(fake_ws.sent[0]),
            {"beginExclusive": 88, "verbose": True},
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
            self.assertEqual(_load_or_init_offset(path, False), 42)

    def test_cursor_advances_for_unrelated_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "monitor_state.json"
            parsed = parse_update_item({
                "update": {
                    "transaction": {
                        "offset": 303,
                        "events": [
                            {
                                "createdEvent": {
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
            })
            cursor = advance_cursor(100, parsed, path)
            self.assertEqual(cursor, 303)
            self.assertEqual(load_last_offset(path), "303")


if __name__ == "__main__":
    unittest.main()
