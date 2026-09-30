import unittest
from decimal import Decimal
from ai_agent.models import PaymentIntent, AgentDecision, Action, ValidationError, WalletContext, strict_json


class ModelTests(unittest.TestCase):
    def test_exact_money(self):
        i = PaymentIntent('Alice', '0.1', 'CC', 'coffee')
        self.assertEqual(i.amount + Decimal('0.2'), Decimal('0.3'))

    def test_invalid_amounts(self):
        for value in ('0', '-1', 'NaN', 'Infinity', '1e99', '1e-99', 'bad', 0.1, True, None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                PaymentIntent('Alice', value, 'CC', '')

    def test_recipient_and_currency(self):
        for recipient, currency in [('', 'CC'), ('Alice or Bob', 'CC'), ('Alice', 'USD'), (None, 'CC')]:
            with self.subTest(recipient=recipient), self.assertRaises(ValidationError):
                PaymentIntent(recipient, '0.1', currency, '')

    def test_schema(self):
        for value in ({}, {'recipient': 'Alice', 'amount': '0.1', 'currency': 'CC', 'purpose': '', 'execute': True}):
            with self.assertRaises(ValidationError):
                PaymentIntent.from_dict(value)

    def test_confidence(self):
        for value in ('-0.1', '1.1', 'NaN', 0.5):
            with self.assertRaises(ValidationError):
                AgentDecision(Action.PROCEED_TO_DAML, value, ())

    def test_invalid_context(self):
        with self.assertRaises(ValidationError):
            WalletContext('-1', '0')

    def test_strict_json(self):
        for raw in ('[]', '{"x":1,"x":2}', '{"x":NaN}', '```json\n{}\n```', '{} trailing'):
            with self.assertRaises(ValidationError):
                strict_json(raw)
