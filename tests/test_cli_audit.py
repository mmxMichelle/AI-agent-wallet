import io
import json
import unittest
from unittest.mock import patch
from ai_agent.cli import main
from ai_agent.logging_utils import audit_record
from ai_agent.orchestrator import GovernedAgent


class CliAuditTests(unittest.TestCase):
    def test_parse_and_assess(self):
        for command in ('parse', 'assess'):
            with patch('sys.stdout', new_callable=io.StringIO) as out:
                self.assertEqual(main([command, 'Pay Alice 0.05 CC for coffee']), 0)
            self.assertIsInstance(json.loads(out.getvalue()), dict)

    def test_demo_yes_no_and_eof(self):
        for answer in ('yes', 'no', ''):
            with patch('builtins.input', return_value=answer), patch('sys.stdout', new_callable=io.StringIO) as out:
                self.assertEqual(main(['demo']), 0)
            text = out.getvalue()
            self.assertIn('no Canton Coin moved', text)
            self.assertIn({'yes': 'WOULD_SUBMIT', 'no': 'DECLINED', '': 'AWAITING_HUMAN'}[answer], text)

    def test_audit_fields_and_no_raw_prompts(self):
        record = audit_record(GovernedAgent().assess('Pay Alice 0.05 CC for coffee'))
        for key in ('request_id', 'timestamp', 'parsed_intent', 'tools_invoked', 'risk_signals',
                    'ai_recommendation', 'ai_confidence', 'deterministic_guardrail_action', 'human_decision'):
            self.assertIn(key, record)
        self.assertFalse({'messages', 'api_key', 'provider', 'chain_of_thought'} & set(record))
        json.dumps(record)

    def test_remote_never_automatic(self):
        with patch('ai_agent.cli.OpenAICompatibleProvider', side_effect=AssertionError('remote called')):
            with patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(['assess', 'Pay Alice 0.05 CC for coffee']), 0)
