import unittest
from decimal import Decimal
from dataclasses import replace
from ai_agent.risk import calculate_risk
from ai_agent.models import PaymentIntent, WalletContext
from ai_agent.memory import MockWalletContextProvider
from ai_agent.policy import load_policy


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.context = MockWalletContextProvider().snapshot()
        self.policy = load_policy()

    def test_known_history(self):
        i = PaymentIntent('Alice', '0.05', 'CC', '')
        risk = calculate_risk(i, self.context, self.policy)
        self.assertEqual(risk, calculate_risk(i, self.context, self.policy))
        self.assertEqual(risk.recipient_transaction_count, 2)
        self.assertEqual(risk.recipient_average_amount, Decimal('0.05'))
        self.assertEqual(risk.amount_vs_recipient_average, 1)
        self.assertTrue(risk.trusted_recipient)
        self.assertFalse(risk.new_recipient)

    def test_new_large_anomaly(self):
        risk = calculate_risk(PaymentIntent('Charlie', '0.6', 'CC', ''), self.context, self.policy)
        self.assertEqual(risk.anomaly_score, 1)
        self.assertEqual(risk.amount_to_balance_ratio, Decimal('0.6'))
        self.assertTrue(risk.new_recipient)

    def test_zero_balance_and_empty_history(self):
        risk = calculate_risk(PaymentIntent('Alice', '0.01', 'CC', ''), WalletContext('0', '0'), self.policy)
        self.assertTrue(risk.insufficient_balance)
        self.assertIsNone(risk.recipient_average_amount)

    def test_repeated_spending(self):
        context = replace(self.context, daily_spend='0.98')
        risk = calculate_risk(PaymentIntent('Alice', '0.05', 'CC', ''), context, self.policy)
        self.assertTrue(risk.exceeds_daily_budget)
