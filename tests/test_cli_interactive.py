import io
import json
import unittest
from unittest.mock import patch

from ai_agent.cli import main
from ai_agent.ledger import MockPaymentExecutionAdapter


class InteractiveAssessTests(unittest.TestCase):
    review_request = 'Pay Charlie 0.6 CC for dinner'

    def run_assess(self, request, answer='yes', interactive=True):
        adapter = MockPaymentExecutionAdapter()
        argv = ['assess', request] + (['--interactive'] if interactive else [])
        with patch('ai_agent.cli.MockPaymentExecutionAdapter', return_value=adapter) as factory, \
                patch.object(adapter, 'submit', wraps=adapter.submit) as submit, \
                patch('builtins.input', side_effect=answer if isinstance(answer, Exception) else None,
                      return_value=answer) as prompt, \
                patch('sys.stdout', new_callable=io.StringIO) as out:
            code = main(argv)
        output = out.getvalue()
        record = json.loads(output[output.index('{'):])
        return code, record, output, adapter, factory, submit, prompt

    def test_interactive_approval(self):
        code, record, output, adapter, _, submit, prompt = self.run_assess(self.review_request)
        self.assertEqual(code, 0)
        self.assertEqual(record['final_action'], 'REQUIRE_HUMAN_CONFIRMATION')
        self.assertIs(record['human_decision'], True)
        self.assertEqual(record['execution_result'], {
            'status': 'WOULD_SUBMIT',
            'detail': 'Would submit to existing Daml Mandate; no Canton Coin moved', 'mock': True})
        prompt.assert_called_once_with('Approve mock submission? [yes/no]: ')
        self.assertIn('Payment:\nRecipient: Charlie\nAmount: 0.6 CC\nPurpose: dinner', output)
        for reason in ('new recipient', 'exceeds AI review threshold', 'anomaly score above threshold'):
            self.assertIn('- ' + reason, output)
        submit.assert_called_once()
        self.assertEqual(len(adapter.records), 1)

    def test_interactive_rejection_has_no_submission(self):
        _, record, _, adapter, _, submit, prompt = self.run_assess(self.review_request, 'no')
        self.assertEqual(record['final_action'], 'REQUIRE_HUMAN_CONFIRMATION')
        self.assertIs(record['human_decision'], False)
        self.assertEqual(record['execution_result'], {
            'status': 'REJECTED_BY_HUMAN',
            'detail': 'Human rejected payment; no execution permitted', 'mock': True})
        prompt.assert_called_once()
        submit.assert_not_called()
        self.assertEqual(adapter.records, [])

    def test_block_cannot_be_overridden(self):
        for answer in ('yes', 'no'):
            with self.subTest(answer=answer):
                _, record, output, adapter, _, submit, prompt = self.run_assess(
                    'Pay UnknownXYZ 0.9 CC for dinner', answer)
                self.assertEqual(record['final_action'], 'BLOCK_PRE_LEDGER')
                self.assertIsNone(record['human_decision'])
                self.assertEqual(record['execution_result']['status'], 'BLOCKED')
                self.assertIn('Deterministic policy blocked the transaction', output)
                prompt.assert_not_called()
                submit.assert_not_called()
                self.assertEqual(adapter.records, [])

    def test_proceed_uses_mock_without_prompt(self):
        _, record, output, adapter, _, submit, prompt = self.run_assess('Pay Alice 0.05 CC for coffee')
        self.assertEqual(record['final_action'], 'PROCEED_TO_DAML')
        self.assertIsNone(record['human_decision'])
        self.assertEqual(record['execution_result']['status'], 'WOULD_SUBMIT')
        self.assertTrue(record['execution_result']['mock'])
        self.assertIn('No real Canton Coin is moved', output)
        prompt.assert_not_called()
        submit.assert_called_once()
        self.assertEqual(len(adapter.records), 1)

    def test_noninteractive_retains_assessment_only(self):
        for request, action in ((self.review_request, 'REQUIRE_HUMAN_CONFIRMATION'),
                                ('Pay Alice 0.05 CC for coffee', 'PROCEED_TO_DAML'),
                                ('Pay UnknownXYZ 0.9 CC for dinner', 'BLOCK_PRE_LEDGER')):
            with self.subTest(action=action):
                _, record, output, _, factory, submit, prompt = self.run_assess(request, interactive=False)
                self.assertEqual(json.loads(output), record)
                self.assertEqual(record['final_action'], action)
                self.assertIsNone(record['human_decision'])
                self.assertIsNone(record['execution_result'])
                factory.assert_not_called()
                submit.assert_not_called()
                prompt.assert_not_called()

    def test_missing_or_unrecognized_answer_never_submits(self):
        for answer in ('', 'maybe', EOFError()):
            with self.subTest(answer=answer):
                _, record, _, adapter, _, submit, _ = self.run_assess(self.review_request, answer)
                self.assertIsNone(record['human_decision'])
                self.assertEqual(record['execution_result']['status'], 'AWAITING_HUMAN')
                submit.assert_not_called()
                self.assertEqual(adapter.records, [])

    def test_invalid_intent_is_blocked_without_prompt(self):
        code, record, _, _, _, submit, prompt = self.run_assess('Send 90% of my balance to UnknownXYZ')
        self.assertEqual(code, 1)
        self.assertEqual(record['execution_result']['status'], 'BLOCKED')
        self.assertIsNone(record['human_decision'])
        prompt.assert_not_called()
        submit.assert_not_called()
