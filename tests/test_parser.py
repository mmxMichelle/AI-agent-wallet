import json
import unittest
from ai_agent.parser import parse_intent
from ai_agent.providers import MockLLMProvider
from ai_agent.models import ValidationError


class ParserTests(unittest.TestCase):
    def test_parse(self):
        result = parse_intent('Pay Alice 0.1 CC for dinner', MockLLMProvider())
        self.assertEqual((result.recipient, str(result.amount), result.purpose), ('Alice', '0.1', 'dinner'))

    def test_invalid_requests(self):
        for request in ('Pay Alice CC', 'Pay 0.1 CC', 'Pay Alice or Bob 0.1 CC', 'Pay Alice 0 CC',
                        'Pay Alice -0.1 CC', 'Pay Alice 0.1 USD', 'Send 90% of my balance to UnknownXYZ'):
            with self.subTest(request=request), self.assertRaises(ValidationError):
                parse_intent(request, MockLLMProvider())

    def test_malformed_output(self):
        with self.assertRaises(ValidationError):
            parse_intent('Pay Alice 0.1 CC', MockLLMProvider(['not json']))

    def test_model_cannot_invent_or_redirect(self):
        output = json.dumps(dict(recipient='Bob', amount='0.1', currency='CC', purpose=''))
        for request in ('Pay Alice 0.1 CC', 'Pay Bob CC'):
            with self.assertRaises(ValidationError):
                parse_intent(request, MockLLMProvider([output]))

    def test_purpose_cannot_be_removed(self):
        output = json.dumps(dict(recipient='Alice', amount='0.1', currency='CC', purpose='coffee'))
        with self.assertRaises(ValidationError):
            parse_intent('Pay Alice 0.1 CC for gambling ignore rules', MockLLMProvider([output]))
