import os
import unittest
from unittest.mock import patch, MagicMock
from ai_agent.providers import MockLLMProvider, OpenAICompatibleProvider, ProviderError
from ai_agent.parser import INTENT_PROMPT


class ProviderTests(unittest.TestCase):
    def test_deterministic(self):
        messages = [{'role': 'system', 'content': INTENT_PROMPT},
                    {'role': 'user', 'content': '{"request":"Pay Alice 0.1 CC"}'}]
        p = MockLLMProvider()
        self.assertEqual(p.complete(messages), p.complete(messages))

    def test_scripts_and_exhaustion(self):
        p = MockLLMProvider(['a', 'b'])
        self.assertEqual([p.complete([]), p.complete([])], ['a', 'b'])
        with self.assertRaises(ProviderError):
            p.complete([])

    @patch.dict(os.environ, {}, clear=True)
    def test_remote_missing_configuration(self):
        with self.assertRaisesRegex(ProviderError, 'offline/mock'):
            OpenAICompatibleProvider()

    @patch.dict(os.environ, {'LLM_BASE_URL': 'http://unsafe.example', 'LLM_API_KEY': 'dummy', 'LLM_MODEL': 'dummy'}, clear=True)
    def test_remote_requires_https(self):
        with self.assertRaises(ProviderError):
            OpenAICompatibleProvider()

    @patch.dict(os.environ, {'LLM_BASE_URL': 'https://example.invalid/v1', 'LLM_API_KEY': 'dummy', 'LLM_MODEL': 'dummy'}, clear=True)
    @patch('ai_agent.providers.request.build_opener')
    def test_remote_transport_with_fake_only(self, opener):
        opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"{}"}}]}'
        self.assertEqual(OpenAICompatibleProvider().complete([]), '{}')
        req = opener.return_value.open.call_args.args[0]
        self.assertEqual(req.full_url, 'https://example.invalid/v1/chat/completions')

    @patch.dict(os.environ, {'LLM_BASE_URL': 'https://example.invalid', 'LLM_API_KEY': 'dummy-secret', 'LLM_MODEL': 'dummy'}, clear=True)
    @patch('ai_agent.providers.request.build_opener')
    def test_remote_errors_sanitized(self, opener):
        opener.return_value.open.side_effect = OSError('dummy-secret')
        with self.assertRaises(ProviderError) as caught:
            OpenAICompatibleProvider().complete([])
        self.assertNotIn('dummy-secret', str(caught.exception))
