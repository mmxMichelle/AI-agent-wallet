from dataclasses import replace
from decimal import Decimal
import socket
import unittest
from unittest.mock import patch
from ai_agent.anomaly import LocalKNNAnomalyModel, default_model, demo_reference_features, model_info
from ai_agent.features import TransactionFeatures, build_features
from ai_agent.memory import MockWalletContextProvider
from ai_agent.models import PaymentIntent, WalletContext, ValidationError
from ai_agent.policy import load_policy
from ai_agent.risk import calculate_risk


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.context = MockWalletContextProvider().snapshot()
        self.policy = load_policy()
        self.intent = PaymentIntent('Alice', '0.05', 'CC', 'coffee')

    def features(self, **kwargs):
        return build_features(self.intent, self.context, self.policy, **kwargs)

    def test_stable_order(self):
        f = self.features()
        self.assertEqual(len(f.vector()), 14)
        self.assertEqual(TransactionFeatures.names()[:3], ('amount', 'amount_to_balance_ratio', 'recipient_transaction_count'))
        self.assertEqual(f.vector(), self.features().vector())

    def test_context_features(self):
        f = self.features()
        self.assertEqual((f.recipient_transaction_count, f.recipient_frequency, f.recipient_average_amount), (2, 1, .05))
        self.assertEqual((f.amount_vs_recipient_average, f.overall_average_amount, f.new_recipient), (1, .05, 0))
        self.assertAlmostEqual(f.daily_spend_ratio, .15)

    def test_empty_and_zero(self):
        f = build_features(self.intent, WalletContext('0', '0'), self.policy)
        self.assertEqual((f.amount_to_balance_ratio, f.recipient_frequency, f.new_recipient), (1, 0, 1))
        self.assertEqual(f.recipient_time_missing, 1)

    def test_timestamp_feature(self):
        self.assertEqual(self.features(observed_at='2026-09-30T10:00:00Z').time_since_last_recipient_payment, 3600)
        self.assertEqual(self.features(observed_at='2026-09-30T10:00:00Z').recipient_time_missing, 0)
        for date in ('bad', '2026-09-01T10:00:00Z', '2026-09-30T10:00:00'):
            with self.assertRaises(ValidationError): self.features(observed_at=date)

    def test_numeric_validation(self):
        for value in (float('nan'), float('inf'), -1, '1', True):
            with self.assertRaises(ValidationError): replace(self.features(), amount=value)
        with self.assertRaises(ValidationError): replace(self.features(), new_recipient=2)


class AnomalyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = demo_reference_features()
        cls.model = default_model()

    def test_fitting_required(self):
        with self.assertRaises(ValidationError): LocalKNNAnomalyModel().score(self.rows[0])

    def test_training_validation(self):
        for rows in ([], self.rows[:3], [None] * 4):
            with self.assertRaises(ValidationError): LocalKNNAnomalyModel().fit(rows)

    def test_deterministic(self):
        other = default_model()
        self.assertEqual(self.model.score(self.rows[0]), other.score(self.rows[0]))
        self.assertEqual(self.rows, demo_reference_features())

    def test_anomaly_ordering_and_range(self):
        context, policy = MockWalletContextProvider().snapshot(), load_policy()
        normal = build_features(PaymentIntent('Alice', '.05', 'CC', ''), context, policy)
        unusual = build_features(PaymentIntent('Charlie', '.6', 'CC', ''), context, policy)
        self.assertGreater(self.model.score(unusual), self.model.score(normal))
        for row in (normal, unusual, *self.rows):
            self.assertTrue(0 <= self.model.score(row) <= 1)

    def test_learning_changes_reference(self):
        row = self.rows[0]
        other = LocalKNNAnomalyModel()
        other.fit([replace(r, amount=r.amount + 100) for r in self.rows])
        self.assertGreater(other.score(row), self.model.score(row))

    def test_local_without_network(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden')):
            self.assertTrue(0 <= default_model().score(self.rows[0]) <= 1)

    def test_model_info(self):
        info = model_info(self.model)
        self.assertEqual(info['reference_transaction_count'], 128)
        self.assertEqual(info['feature_count'], 14)
        self.assertIn('synthetic', info['training_source'])

    def test_score_cannot_relax_policy(self):
        context, policy = MockWalletContextProvider().snapshot(), load_policy()
        risk = calculate_risk(PaymentIntent('Alice', '5', 'CC', ''), context, policy, Decimal('0'))
        self.assertTrue(risk.insufficient_balance)
        self.assertTrue(risk.exceeds_hard_maximum)
