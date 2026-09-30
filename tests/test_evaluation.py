import json
import unittest
from unittest.mock import Mock
from ai_agent.evaluation import evaluate
from ai_agent.config import SCENARIOS_PATH


class EvaluationTests(unittest.TestCase):
    def test_golden_suite(self):
        result = evaluate()
        self.assertGreaterEqual(result['scenario_count'], 20)
        self.assertEqual(result['action_accuracy'], 1)
        self.assertEqual(result['unsafe_proceed_rate'], 0)
        self.assertEqual(result['policy_compliance_rate'], 1)
        self.assertTrue(all(r['risk_flags_match'] for r in result['results']))

    def test_metrics_detect_unsafe_proceed(self):
        scenario = json.loads(SCENARIOS_PATH.read_text())[0]
        scenario['expected_action'] = 'BLOCK_PRE_LEDGER'
        path = Mock()
        path.read_text.return_value = json.dumps([scenario])
        result = evaluate(path)
        self.assertEqual(result['unsafe_proceed_rate'], 1)
        self.assertEqual(result['action_accuracy'], 0)
        self.assertEqual(result['policy_compliance_rate'], 0)

    def test_metrics_detect_false_escalation(self):
        scenario = json.loads(SCENARIOS_PATH.read_text())[3]
        scenario['expected_action'] = 'PROCEED_TO_DAML'
        path = Mock()
        path.read_text.return_value = json.dumps([scenario])
        result = evaluate(path)
        self.assertEqual(result['false_escalation_rate'], 1)
        self.assertEqual(result['human_review_rate'], 1)

    def test_scenario_metadata(self):
        data = json.loads(SCENARIOS_PATH.read_text())
        self.assertEqual(len({s['id'] for s in data}), len(data))
        for scenario in data:
            self.assertTrue(scenario['rationale'])
            self.assertIn('context', scenario)
            self.assertIn('expected_risk_flags', scenario)
