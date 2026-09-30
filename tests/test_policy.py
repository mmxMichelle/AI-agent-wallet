from dataclasses import replace
import unittest
from ai_agent.policy import load_policy
from ai_agent.models import ValidationError


class PolicyTests(unittest.TestCase):
    def test_demo_policy(self):
        p = load_policy()
        self.assertIn('DEMO', p.label)
        self.assertEqual(str(p.daily_budget), '1.0')

    def test_invalid_policy(self):
        for changes in ({'daily_budget': '-1'}, {'maximum_balance_fraction': '1.1'},
                        {'new_recipient_requires_review': 'false'}, {'trusted_recipients': 'Alice'}):
            with self.assertRaises(ValidationError):
                replace(load_policy(), **changes)
