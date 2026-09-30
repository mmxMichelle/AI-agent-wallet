"""BYOM/BYOK regressions: every HTTP response is supplied by a fake transport."""
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from ai_agent.cli import main
from ai_agent.logging_utils import audit_record
from ai_agent.models import Action, PaymentIntent
from ai_agent.orchestrator import GovernedAgent
from ai_agent.providers import (MockLLMProvider, OllamaProvider, OpenAICompatibleProvider,
                                ProviderError, create_provider, _http_transport)

SECRET = 'test-only-credential-DO-NOT-LOG'
ENV = {'LLM_BASE_URL': 'https://example.invalid/v1', 'LLM_MODEL': 'user-model',
       'LLM_API_KEY': SECRET, 'OLLAMA_MODEL': 'user-local-model'}
INTENT = json.dumps({'recipient': 'Alice', 'amount': '0.05', 'currency': 'CC', 'purpose': 'coffee'})
DECISION = json.dumps({'type': 'decision', 'action': 'PROCEED_TO_DAML', 'confidence': '1',
                       'reasons': ['recommendation'], 'policy_references': []})


def envelope(mode, content):
    if mode == 'ollama':
        return json.dumps({'message': {'content': content}, 'done': True}).encode()
    return json.dumps({'choices': [{'message': {'content': content}}]}).encode()


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV, clear=True)
        self.env.start()
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden'))
        self.network.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.network.stop)

    def cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(args))
        return code, output.getvalue()

    def test_mock_default_despite_credentials(self):
        self.assertIsInstance(create_provider(), MockLLMProvider)
        self.assertIsInstance(GovernedAgent().provider, MockLLMProvider)
        code, output = self.cli('assess', 'Pay Alice 0.05 CC for coffee')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['final_action'], 'PROCEED_TO_DAML')

    def test_factory_all_modes(self):
        for mode, cls in [('mock', MockLLMProvider), ('ollama', OllamaProvider),
                          ('openai-compatible', OpenAICompatibleProvider)]:
            with self.subTest(mode=mode):
                self.assertIsInstance(create_provider(mode), cls)

    def test_unknown_provider_rejected_without_echoing_config(self):
        with self.assertRaises(ProviderError) as caught:
            create_provider(SECRET)
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertIn('mock, openai-compatible, ollama', str(caught.exception))
        code, output = self.cli('assess', 'Pay Alice 0.05 CC', '--provider', 'xyz')
        self.assertEqual(code, 1)
        self.assertIn('Unknown LLM provider', output)

    def test_environment_selects_provider_and_configuration(self):
        for mode in ('ollama', 'openai-compatible'):
            with self.subTest(mode=mode), patch.dict(os.environ, {'LLM_PROVIDER': mode}):
                provider = create_provider()
                self.assertEqual(provider.model, ENV['OLLAMA_MODEL' if mode == 'ollama' else 'LLM_MODEL'])
        with patch.dict(os.environ, {'OLLAMA_BASE_URL': 'http://127.0.0.1:8888'}):
            self.assertEqual(create_provider('ollama').base, 'http://127.0.0.1:8888')

    def test_cli_overrides_provider_model_and_endpoint_environment(self):
        for mode in ('ollama', 'openai-compatible'):
            fake = Mock(return_value=envelope(mode, INTENT))
            with self.subTest(mode=mode), patch.dict(os.environ, {'LLM_PROVIDER': 'invalid'}), \
                    patch('ai_agent.providers._http_transport', fake):
                code, _ = self.cli('parse', 'Pay Alice 0.05 CC for coffee', '--provider', mode,
                                   '--model', 'cli-model', '--base-url', 'http://localhost:1234/v1')
                self.assertEqual(code, 0)
                req = fake.call_args.args[0]
                self.assertEqual(json.loads(req.data)['model'], 'cli-model')
                self.assertTrue(req.full_url.startswith('http://localhost:1234/v1/'))
        with patch.dict(os.environ, {'LLM_PROVIDER': 'ollama'}):
            self.assertEqual(self.cli('parse', 'Pay Alice 0.05 CC for coffee', '--provider', 'mock')[0], 0)

    def test_cli_environment_selection(self):
        fake = Mock(return_value=envelope('ollama', INTENT))
        with patch.dict(os.environ, {'LLM_PROVIDER': 'ollama'}), patch('ai_agent.providers._http_transport', fake):
            self.assertEqual(self.cli('parse', 'Pay Alice 0.05 CC for coffee')[0], 0)
        self.assertEqual(fake.call_args.args[0].full_url, 'http://localhost:11434/api/chat')

    def test_missing_configuration_fails_before_network(self):
        for mode, env, expected in [
            ('openai-compatible', {}, 'LLM_BASE_URL and LLM_MODEL'),
            ('openai-compatible', {'LLM_BASE_URL': ENV['LLM_BASE_URL'], 'LLM_MODEL': 'chosen'}, 'LLM_API_KEY'),
            ('ollama', {}, 'OLLAMA_MODEL')]:
            with self.subTest(mode=mode, env=env), patch.dict(os.environ, env, clear=True):
                code, output = self.cli('assess', 'Pay Alice 0.05 CC', '--provider', mode)
                self.assertEqual(code, 1)
                self.assertIn(expected, output)
                self.assertIn('No payment action was taken', output)

    def test_information_and_eval_ignore_external_configuration(self):
        with patch.dict(os.environ, {'LLM_PROVIDER': 'invalid'}):
            code, output = self.cli('providers')
            self.assertEqual(code, 0)
            for name in ('mock', 'openai-compatible', 'ollama'):
                self.assertIn(name, output)
            self.assertEqual(self.cli('eval')[0], 0)

    def test_fake_http_wire_and_normalization(self):
        for mode in ('openai-compatible', 'ollama'):
            fake = Mock(return_value=envelope(mode, INTENT))
            provider = create_provider(mode, transport=fake)
            self.assertEqual(provider.complete([{'role': 'tool', 'content': '{}'}]), INTENT)
            req = fake.call_args.args[0]
            body = json.loads(req.data)
            self.assertEqual(body['messages'], [{'role': 'user', 'content': '{}'}])
            self.assertFalse(body['stream'])
            self.assertNotIn('tools', body)
            self.assertEqual(fake.call_args.kwargs, {'timeout': 20, 'limit': 65537})
            if mode == 'ollama':
                self.assertEqual(req.full_url, 'http://localhost:11434/api/chat')
                self.assertIsNone(req.get_header('Authorization'))
                self.assertEqual(body['format'], 'json')
            else:
                self.assertEqual(req.full_url, 'https://example.invalid/v1/chat/completions')
                self.assertEqual(req.get_header('Authorization'), 'Bearer ' + SECRET)

    def test_loopback_compatible_endpoint_needs_no_key(self):
        for host in ('localhost', '127.0.0.1', '[::1]'):
            with self.subTest(host=host), patch.dict(os.environ, {'LLM_API_KEY': ''}):
                fake = Mock(return_value=envelope('openai-compatible', '{}'))
                provider = create_provider('openai-compatible', base_url=f'http://{host}:1234/v1', transport=fake)
                self.assertEqual(provider.complete([]), '{}')
                self.assertIsNone(fake.call_args.args[0].get_header('Authorization'))

    def test_invalid_urls_rejected_without_echoing(self):
        for url in ('http://example.invalid', 'https://user:password@example.invalid',
                    'https://example.invalid?key=' + SECRET, 'https://example.invalid/#fragment',
                    'file:///tmp/foo', 'https://example.invalid:invalid',
                    'http://localhost.example.invalid', 'https://example.invalid/\npath'):
            for mode in ('openai-compatible', 'ollama'):
                with self.subTest(url=url, mode=mode), self.assertRaises(ProviderError) as caught:
                    create_provider(mode, base_url=url)
                self.assertNotIn(url, str(caught.exception))
                self.assertNotIn(SECRET, str(caught.exception))

    def test_transport_sanitizes_errors_and_cli_audit(self):
        for mode in ('openai-compatible', 'ollama'):
            for error in (OSError(SECRET), ValueError(SECRET), HTTPError(ENV['LLM_BASE_URL'], 401, SECRET, {}, None)):
                fake = Mock(side_effect=error)
                provider = create_provider(mode, transport=fake)
                with self.assertRaises(ProviderError) as caught:
                    provider.complete([])
                self.assertNotIn(SECRET, str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)
                with patch('ai_agent.providers._http_transport', fake):
                    code, output = self.cli('assess', 'Pay Alice 0.05 CC for coffee', '--provider', mode)
                self.assertEqual(code, 1)
                self.assertNotIn(SECRET, output)
                self.assertEqual(json.loads(output)['final_action'], 'BLOCK_PRE_LEDGER')

    def test_malformed_responses_fail_closed(self):
        for mode in ('openai-compatible', 'ollama'):
            invalid = [b'bad', b'[]', b'{}', b'x' * 65537,
                       envelope(mode, None), envelope(mode, 'not json'),
                       envelope(mode, '{"x":1,"x":2}'), envelope(mode, '[]'),
                       envelope(mode, '{"x":NaN}'), envelope(mode, 'x' * 10001),
                       envelope(mode, '```json\n{}\n```')]
            for raw in invalid:
                with self.subTest(mode=mode, raw=raw[:40]):
                    provider = create_provider(mode, transport=Mock(return_value=raw))
                    with self.assertRaisesRegex(ProviderError, 'could not be safely parsed'):
                        provider.complete([])

    def test_vendor_tool_calls_and_truncated_outputs_rejected(self):
        responses = [
            ('ollama', {'message': {'content': '{}'}, 'done': False}),
            ('ollama', {'message': {'content': '{}'}, 'done': True, 'done_reason': 'length'}),
            ('ollama', {'message': {'content': '{}', 'tool_calls': [{}]}, 'done': True}),
            ('openai-compatible', {'choices': [{'message': {'content': '{}'}, 'finish_reason': 'length'}]}),
            ('openai-compatible', {'choices': [{'message': {'content': '{}', 'tool_calls': [{}]}}]}),
        ]
        for mode, response in responses:
            with self.subTest(mode=mode), self.assertRaises(ProviderError):
                create_provider(mode, transport=Mock(return_value=json.dumps(response).encode())).complete([])

    def test_echoed_credential_rejected_before_audit(self):
        raw = json.loads(INTENT)
        raw['purpose'] = SECRET
        provider = create_provider('openai-compatible', transport=Mock(return_value=envelope('openai-compatible', json.dumps(raw))))
        result = GovernedAgent(provider).assess('Pay Alice 0.05 CC for coffee')
        self.assertEqual(result.action, Action.BLOCK_PRE_LEDGER)
        self.assertNotIn(SECRET, json.dumps(audit_record(result)))

    def test_response_cannot_bypass_allowlist(self):
        attack = json.dumps({'type': 'tool', 'name': 'submit_command', 'arguments': {}})
        for mode in ('mock', 'openai-compatible', 'ollama'):
            provider = MockLLMProvider([attack]) if mode == 'mock' else create_provider(mode, transport=Mock(return_value=envelope(mode, attack)))
            result = GovernedAgent(provider).assess(PaymentIntent('Alice', '0.05', 'CC', 'coffee'))
            self.assertEqual(result.action, Action.REQUIRE_HUMAN_CONFIRMATION)
            self.assertEqual(result.tools_invoked, ())

    def test_provider_cannot_change_guardrail_semantics(self):
        for amount, recipient, expected in [('0.05', 'Alice', Action.PROCEED_TO_DAML),
                                            ('0.6', 'Charlie', Action.REQUIRE_HUMAN_CONFIRMATION),
                                            ('5', 'Alice', Action.BLOCK_PRE_LEDGER)]:
            results = []
            for mode in ('mock', 'openai-compatible', 'ollama'):
                provider = MockLLMProvider([DECISION]) if mode == 'mock' else create_provider(mode, transport=Mock(return_value=envelope(mode, DECISION)))
                result = GovernedAgent(provider).assess(PaymentIntent(recipient, amount, 'CC', 'coffee'))
                self.assertEqual(result.action, expected)
                results.append((result.risk, result.guardrail))
            self.assertEqual(results[0], results[1])
            self.assertEqual(results[0], results[2])

    def test_failure_after_intent_escalates_and_hard_blocks_remain(self):
        for mode in ('openai-compatible', 'ollama'):
            for amount, expected in [('0.05', Action.REQUIRE_HUMAN_CONFIRMATION), ('5', Action.BLOCK_PRE_LEDGER)]:
                intent = json.loads(INTENT)
                intent['amount'] = amount
                fake = Mock(side_effect=[envelope(mode, json.dumps(intent)), OSError(SECRET)])
                result = GovernedAgent(create_provider(mode, transport=fake)).assess(f'Pay Alice {amount} CC for coffee')
                self.assertEqual(result.action, expected)
                self.assertNotIn(SECRET, json.dumps(audit_record(result)))

    def test_no_redirects_or_ambient_proxies(self):
        with patch('ai_agent.providers.request.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{}'
            _http_transport(Mock(), timeout=20, limit=65537)
            proxy, redirect = opener.call_args.args
            self.assertEqual(proxy.proxies, {})
            self.assertIsNone(redirect().redirect_request(None, None, None, None, None, None))

    def test_entire_ai_suite_offline_with_network_disabled(self):
        # Run every existing AI test plus eval with network and legacy imports blocked.
        # Exclude this file to avoid recursive subprocesses.
        script = '''
import importlib.abc, os, socket, sys, unittest
os.environ.clear()
def forbidden(*args, **kwargs):
    raise AssertionError('Network forbidden')
socket.socket.connect = forbidden
socket.create_connection = forbidden
socket.getaddrinfo = forbidden
class NoLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname in ('c8lab', 'daml'):
            raise AssertionError('Legacy runtime forbidden')
sys.meta_path.insert(0, NoLegacy())
suite = unittest.TestSuite()
from pathlib import Path
for path in sorted(Path('tests').glob('test_*.py')):
    if path.name != 'test_provider_configuration.py':
        suite.addTests(unittest.defaultTestLoader.discover('tests', pattern=path.name))
result = unittest.TextTestRunner().run(suite)
from ai_agent.evaluation import evaluate
report = evaluate()
assert all(row['correct'] and row['risk_flags_match'] for row in report['results'])
sys.exit(not result.wasSuccessful())
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
