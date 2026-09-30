from __future__ import annotations

import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PY_DIR = pathlib.Path(__file__).resolve().parent
if str(PY_DIR) not in sys.path:
    sys.path.insert(0, str(PY_DIR))

import demo_ui as ui  # noqa: E402


class DemoUiTests(unittest.TestCase):
    def test_policy_decision(self) -> None:
        self.assertEqual(ui.policy_decision(ui.Decimal("0.10"), ui.Decimal("0.20")), "AUTO APPROVED")
        self.assertEqual(ui.policy_decision(ui.Decimal("0.20"), ui.Decimal("0.20")), "HUMAN APPROVAL REQUIRED")

    def test_format_cc(self) -> None:
        self.assertEqual(ui.format_cc("0.1"), "0.10")
        self.assertEqual(ui.format_cc(ui.Decimal("4.5")), "4.50")

    def test_sum_holdings(self) -> None:
        total = ui.sum_holdings([
            {"amount": "4.5", "instrument": "Amulet"},
            {"amount": "1.0", "instrument": "Other"},
            {"amount": "0.5", "instrument": "Amulet"},
        ])
        self.assertEqual(total, ui.Decimal("5.0"))

    def test_state_defaults(self) -> None:
        state = ui.DemoState()
        self.assertEqual(state.spender_party, ui.DEFAULT_SPENDER)
        self.assertEqual(state.recipient_party, ui.DEFAULT_RECIPIENT)
        self.assertEqual(state.approval_threshold, ui.DEFAULT_THRESHOLD)
        self.assertEqual(state.spending_cap, ui.DEFAULT_CAP)


if __name__ == "__main__":
    unittest.main()
