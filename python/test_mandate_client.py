from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PY_DIR = pathlib.Path(__file__).resolve().parent
if str(PY_DIR) not in sys.path:
    sys.path.insert(0, str(PY_DIR))

import mandate_client as mc  # noqa: E402


class MandateClientBuilderTests(unittest.TestCase):
    def test_template_id_uses_package_ref(self) -> None:
        self.assertEqual(
            mc.mandate_template_id("MandateProposal"),
            "#daml-starter-0.0.1:Mandate:MandateProposal",
        )
        self.assertEqual(
            mc.mandate_template_id("Mandate", package_ref="custom-pkg"),
            "#custom-pkg:Mandate:Mandate",
        )
        self.assertEqual(
            mc.mandate_template_id(
                "MandateProposal",
                package_ref="b46673671ac53ba0225aaed8e8059279a5ed77d0ec014a2c72ca3f45521ca828",
            ),
            "b46673671ac53ba0225aaed8e8059279a5ed77d0ec014a2c72ca3f45521ca828:Mandate:MandateProposal",
        )

    def test_template_id_preserves_hash_prefix(self) -> None:
        self.assertEqual(
            mc.mandate_template_id("MandateProposal", package_ref="#my-package"),
            "#my-package:Mandate:MandateProposal",
        )

    def test_create_proposal_command_shape(self) -> None:
        command = mc.create_proposal_command(
            owner="Owner::123",
            spender="Spender::456",
            allowed_recipient="Recipient::789",
            cap="1000",
            approval_threshold="200",
            expires_at="2026-08-29T23:59:59Z",
            package_ref="#pkg-ref",
        )
        self.assertEqual(
            command,
            {
                "CreateCommand": {
                    "templateId": "#pkg-ref:Mandate:MandateProposal",
                    "createArguments": {
                        "owner": "Owner::123",
                        "spender": "Spender::456",
                        "allowedRecipient": "Recipient::789",
                        "approvalThreshold": "200",
                        "cap": "1000",
                        "expiresAt": "2026-08-29T23:59:59Z",
                    },
                }
            },
        )

    def test_accept_proposal_command_shape(self) -> None:
        command = mc.accept_proposal_command("cid-1", package_ref="#pkg-ref")
        self.assertEqual(
            command,
            {
                "ExerciseCommand": {
                    "templateId": "#pkg-ref:Mandate:MandateProposal",
                    "contractId": "cid-1",
                    "choice": "Accept",
                    "choiceArgument": {},
                }
            },
        )

    def test_request_high_value_command_shape(self) -> None:
        command = mc.request_high_value_command(
            "cid-2",
            amount="350",
            recipient="Recipient::789",
            purpose="Hackathon test payment",
            package_ref="#pkg-ref",
        )
        self.assertEqual(
            command,
            {
                "ExerciseCommand": {
                    "templateId": "#pkg-ref:Mandate:Mandate",
                    "contractId": "cid-2",
                    "choice": "RequestHighValue",
                    "choiceArgument": {
                        "amount": "350",
                        "recipient": "Recipient::789",
                        "purpose": "Hackathon test payment",
                    },
                }
            },
        )

    def test_approve_reject_command_shape(self) -> None:
        self.assertEqual(
            mc.approve_command("cid-3", package_ref="#pkg-ref"),
            {
                "ExerciseCommand": {
                    "templateId": "#pkg-ref:Mandate:PendingPayment",
                    "contractId": "cid-3",
                    "choice": "Approve",
                    "choiceArgument": {},
                }
            },
        )
        self.assertEqual(
            mc.reject_command("cid-4", package_ref="#pkg-ref"),
            {
                "ExerciseCommand": {
                    "templateId": "#pkg-ref:Mandate:PendingPayment",
                    "contractId": "cid-4",
                    "choice": "Reject",
                    "choiceArgument": {},
                }
            },
        )

    def test_cli_parsing(self) -> None:
        parser = mc.build_parser()
        args = parser.parse_args(
            [
                "create-proposal",
                "--owner",
                "Owner::123",
                "--spender",
                "Spender::456",
                "--allowed-recipient",
                "Recipient::789",
                "--cap",
                "1000",
                "--approval-threshold",
                "200",
                "--expires-at",
                "2026-08-29T23:59:59Z",
            ]
        )
        self.assertEqual(args.cmd, "create-proposal")
        self.assertEqual(args.owner, "Owner::123")
        self.assertEqual(args.spender, "Spender::456")
        self.assertEqual(args.allowed_recipient, "Recipient::789")
        self.assertEqual(args.cap, "1000")
        self.assertEqual(args.approval_threshold, "200")
        self.assertEqual(args.expires_at, "2026-08-29T23:59:59Z")
        self.assertEqual(args.package_ref, mc.DEFAULT_PACKAGE_REF)

    def test_settle_cli_parsing(self) -> None:
        parser = mc.build_parser()
        args = parser.parse_args(
            [
                "settle",
                "--from-party",
                "Spender::456",
                "--to-party",
                "Recipient::789",
                "--amount",
                "350",
            ]
        )
        self.assertEqual(args.cmd, "settle")
        self.assertEqual(args.from_party, "Spender::456")
        self.assertEqual(args.to_party, "Recipient::789")
        self.assertEqual(args.amount, "350")

    @mock.patch.object(mc.c8lab, "holdings", return_value=[])
    @mock.patch.object(mc.c8lab, "transfer")
    def test_settle_fails_on_zero_holdings(self, transfer_mock: mock.Mock, holdings_mock: mock.Mock) -> None:
        with self.assertRaises(mc.MandateClientError) as ctx:
            mc.settle_payment("Spender::456", "Recipient::789", "350")
        self.assertIn("Sender has no Canton Coin holdings", str(ctx.exception))
        holdings_mock.assert_called_once_with("Spender::456")
        transfer_mock.assert_not_called()

    @mock.patch.object(mc.c8lab, "holdings", return_value=[{"contractId": "cid-1"}])
    @mock.patch.object(mc.c8lab, "transfer", return_value={
        "transferKind": "direct",
        "result": {"ok": True},
    })
    def test_settle_direct_transfer(self, transfer_mock: mock.Mock, holdings_mock: mock.Mock) -> None:
        result = mc.settle_payment("Spender::456", "Recipient::789", "350")
        self.assertEqual(result["transferKind"], "direct")
        transfer_mock.assert_called_once_with("Spender::456", "Recipient::789", "350")
        holdings_mock.assert_called_once_with("Spender::456")

    @mock.patch.object(mc.c8lab, "holdings", return_value=[{"contractId": "cid-1"}])
    @mock.patch.object(mc.c8lab, "transfer", return_value={
        "transferKind": "offer",
        "instructionCid": "instr-123",
        "result": {"ok": True},
    })
    def test_settle_offer_transfer(self, transfer_mock: mock.Mock, holdings_mock: mock.Mock) -> None:
        result = mc.settle_payment("Spender::456", "Recipient::789", "350")
        self.assertEqual(result["transferKind"], "offer")
        self.assertEqual(result["instructionCid"], "instr-123")
        transfer_mock.assert_called_once_with("Spender::456", "Recipient::789", "350")
        holdings_mock.assert_called_once_with("Spender::456")


if __name__ == "__main__":
    unittest.main()
