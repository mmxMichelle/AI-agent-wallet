import unittest
from ai_agent.tools import ReadOnlyTools, ToolRequest
from ai_agent.models import PaymentIntent, ValidationError
from ai_agent.memory import MockWalletContextProvider
from ai_agent.policy import load_policy


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.context = MockWalletContextProvider().snapshot()
        self.tools = ReadOnlyTools(PaymentIntent('Alice', '0.05', 'CC', 'coffee'), self.context, load_policy())

    def test_allowlist_and_read_only(self):
        self.assertEqual(len(self.tools.names), 5)
        for name in self.tools.names:
            self.tools.invoke(ToolRequest(name, {}))
        self.assertEqual(self.context, MockWalletContextProvider().snapshot())

    def test_forbidden_tools(self):
        for name in ('transfer', 'settle', 'approve', 'submit', 'shell', 'http', 'read_file', '__dict__'):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                self.tools.invoke(ToolRequest(name, {}))

    def test_arguments_cannot_override_context(self):
        for args in ({'balance': '100'}, {'recipient': 'Bob'}, {'path': '/tmp'}, [], None):
            with self.assertRaises(ValidationError):
                self.tools.invoke(ToolRequest('get_balance', args))

    def test_bad_request_schema(self):
        with self.assertRaises(ValidationError):
            ToolRequest.from_dict({'type': 'tool', 'name': 'get_balance'})
