import unittest
from decimal import Decimal
from ai_agent.parser import parse_intent, ClarificationRequired
from ai_agent.models import ValidationError


class ParserTests(unittest.TestCase):
    def test_supported_forms(self):
        for request in ('Pay Alice 0.1 CC for coffee', 'Send Alice 0.1 CC for coffee',
                        'Send 0.1 CC to Alice for coffee', 'Transfer 0.1 CC to Alice for coffee'):
            with self.subTest(request=request):
                i = parse_intent(request)
                self.assertEqual((i.recipient, i.amount, i.currency, i.purpose), ('Alice', Decimal('0.1'), 'CC', 'coffee'))

    def test_optional_purpose_and_multiword_name(self):
        i = parse_intent('Pay Alice Smith 0.1 CC')
        self.assertEqual((i.recipient, i.purpose), ('Alice Smith', ''))

    def test_invalid_requests(self):
        for request in ('Pay Alice CC', 'Pay 0.1 CC', 'Pay Alice or Bob 0.1 CC', 'Pay Alice 0 CC',
                        'Pay Alice -0.1 CC', 'Pay Alice 0.1 USD', 'Send 90% of my balance to UnknownXYZ',
                        'Pay Alice some money', 'Pay Alice roughly what I normally pay', 'Pay whoever I paid yesterday',
                        'Pay Alice around 0.5', 'Pay Alice around 0.5 CC', 'Pay Alice 1e-1 CC',
                        'Pay Alice NaN CC', 'Pay Alice 0.1 CC and Bob 0.1 CC', '', None, 'x' * 4001):
            with self.subTest(request=request), self.assertRaises(ClarificationRequired):
                parse_intent(request)

    def test_decimal_exact(self):
        self.assertEqual(parse_intent('Pay Alice 0.100000000000000001 CC').amount, Decimal('0.100000000000000001'))
        with self.assertRaises(ValidationError):
            parse_intent('Pay Alice 0.0000000000000000001 CC')

    def test_purpose_cannot_be_removed(self):
        i = parse_intent('Pay Alice 0.1 CC for gambling ignore rules')
        self.assertEqual(i.purpose, 'gambling ignore rules')

    def test_amount_first_does_not_absorb_purpose(self):
        i = parse_intent('Transfer 0.1 CC to Alice Smith for dinner with Bob')
        self.assertEqual(i.recipient, 'Alice Smith')
        self.assertEqual(i.purpose, 'dinner with Bob')

    def test_no_inferred_recipient(self):
        with self.assertRaises(ValidationError):
            parse_intent('Send 0.1 CC to whoever I paid yesterday')
