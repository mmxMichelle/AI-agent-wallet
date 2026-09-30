import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ai_agent.models import PaymentIntent, ValidationError
from ai_agent.orchestrator import GovernedAgent
from ai_agent.ledger import ExecutionController, MockPaymentExecutionAdapter
from ai_agent.legacy_adapter import LegacyDamlPaymentExecutionAdapter


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.agent = GovernedAgent()
        self.adapter = MockPaymentExecutionAdapter()
        self.controller = ExecutionController(self.adapter, self.agent.context, self.agent.policy)

    def test_mock_only(self):
        assessment = self.agent.assess('Pay Alice 0.05 CC for coffee')
        result = self.controller.execute(assessment)
        self.assertEqual(result.status, 'WOULD_SUBMIT')
        self.assertTrue(result.mock)
        self.assertEqual(len(self.adapter.records), 1)
        self.assertEqual(self.controller.execute(assessment).status, 'ALREADY_HANDLED')

    def test_block_cannot_be_approved(self):
        assessment = self.agent.assess('Pay Alice 5 CC for coffee')
        self.assertEqual(self.controller.execute(assessment, True).status, 'BLOCKED')
        self.assertEqual(self.adapter.records, [])

    def test_review_waits_then_yes(self):
        assessment = self.agent.assess('Pay Charlie 0.6 CC for dinner')
        self.assertEqual(self.controller.execute(assessment).status, 'AWAITING_HUMAN')
        self.assertEqual(self.adapter.records, [])
        self.assertEqual(self.controller.execute(assessment, True).status, 'WOULD_SUBMIT')

    def test_no_is_final(self):
        assessment = self.agent.assess('Pay Charlie 0.6 CC for dinner')
        self.assertEqual(self.controller.execute(assessment, False).status, 'DECLINED')
        self.assertEqual(self.controller.execute(assessment, True).status, 'ALREADY_HANDLED')
        self.assertEqual(self.adapter.records, [])

    def test_string_yes_not_authority(self):
        with self.assertRaises(ValidationError):
            self.controller.execute(self.agent.assess('Pay Charlie 0.6 CC for dinner'), 'yes')

    def test_refresh_before_execution(self):
        assessment = self.agent.assess('Pay Alice 0.05 CC for coffee')
        self.agent.context.context = replace(self.agent.context.context, balance='0')
        self.assertEqual(self.controller.execute(assessment, True).status, 'BLOCKED')
        self.assertEqual(self.adapter.records, [])

    def test_legacy_disabled(self):
        adapter = LegacyDamlPaymentExecutionAdapter('cid', 'spender', '0.2', {'Alice': 'party'})
        with self.assertRaises(ValidationError):
            adapter.submit(PaymentIntent('Alice', '0.05', 'CC', ''))

    def test_legacy_wraps_commands_with_fake_runtime(self):
        fake = SimpleNamespace(charge_command=Mock(return_value={'charge': True}),
                               request_high_value_command=Mock(return_value={'pending': True}), submit_command=Mock())
        with patch.dict(sys.modules, {'python': SimpleNamespace(mandate_client=fake), 'python.mandate_client': fake}):
            for amount, builder in [('0.05', fake.charge_command), ('0.6', fake.request_high_value_command)]:
                adapter = LegacyDamlPaymentExecutionAdapter('cid', 'spender', '0.2', {'Alice': 'party'}, enabled=True)
                result = adapter.submit(PaymentIntent('Alice', amount, 'CC', 'coffee'))
                self.assertEqual(result.status, 'SUBMITTED_TO_DAML')
                builder.assert_called_with('cid', amount, 'party', 'coffee')
                with self.assertRaises(ValidationError):
                    adapter.submit(PaymentIntent('Alice', amount, 'CC', 'coffee'))
        self.assertEqual(fake.submit_command.call_count, 2)
