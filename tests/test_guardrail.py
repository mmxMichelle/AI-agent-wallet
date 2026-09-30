import unittest
from dataclasses import replace
from ai_agent.models import Action, AgentDecision, PaymentIntent, SEVERITY
from ai_agent.memory import MockWalletContextProvider
from ai_agent.policy import load_policy
from ai_agent.risk import calculate_risk
from ai_agent.guardrail import validate


class GuardrailTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()
        self.risk = calculate_risk(PaymentIntent('Alice', '0.05', 'CC', ''), MockWalletContextProvider().snapshot(), self.policy)

    def test_monotonic_all_combinations(self):
        for action in Action:
            for risk in (self.risk, replace(self.risk, new_recipient=True), replace(self.risk, insufficient_balance=True)):
                result = validate(AgentDecision(action, '0.95', ()), risk, self.policy)
                self.assertGreaterEqual(SEVERITY[result.action], SEVERITY[action])
                self.assertGreaterEqual(SEVERITY[result.action], SEVERITY[result.rule_action])

    def test_hard_rules(self):
        for flag in ('insufficient_balance', 'blocked_category', 'exceeds_hard_maximum', 'exceeds_balance_fraction'):
            result = validate(AgentDecision(Action.PROCEED_TO_DAML, '1', ()), replace(self.risk, **{flag: True}), self.policy)
            self.assertEqual(result.action, Action.BLOCK_PRE_LEDGER)

    def test_low_confidence(self):
        result = validate(AgentDecision(Action.PROCEED_TO_DAML, '0.69', ()), self.risk, self.policy)
        self.assertEqual(result.action, Action.REQUIRE_HUMAN_CONFIRMATION)

    def test_confidence_boundary(self):
        result = validate(AgentDecision(Action.PROCEED_TO_DAML, '0.7', ()), self.risk, self.policy)
        self.assertEqual(result.action, Action.PROCEED_TO_DAML)
