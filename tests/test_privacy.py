"""Privacy boundary: no AI transport, dependency, environment setup or socket use."""
import ast
import json
from pathlib import Path
import subprocess
import sys
import unittest


class PrivacyTests(unittest.TestCase):
    def test_no_active_inference_configuration(self):
        forbidden = ('LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL', 'LLM_PROVIDER', 'OLLAMA_MODEL',
                     'OLLAMA_BASE_URL', 'OpenAICompatibleProvider', 'MockLLMProvider')
        paths = list(Path('ai_agent').glob('*.py')) + list(Path('config').glob('*')) + [Path('.env.example')]
        for path in paths:
            if path.is_file():
                for token in forbidden:
                    self.assertNotIn(token, path.read_text(), str(path))
        self.assertFalse(Path('ai_agent/providers.py').exists())

    def test_no_network_or_cloud_imports_in_local_layer(self):
        forbidden = {'openai', 'ollama', 'requests', 'httpx', 'urllib', 'socket', 'http', 'subprocess'}
        for path in Path('ai_agent').glob('*.py'):
            if path.name == 'legacy_adapter.py':
                continue  # Explicit execution boundary remains separate and opt-in.
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import): names = [n.name for n in node.names]
                elif isinstance(node, ast.ImportFrom): names = [node.module or '']
                else: continue
                self.assertFalse({n.split('.')[0] for n in names} & forbidden, str(path))

    def test_cli_has_no_inference_flags(self):
        result = subprocess.run([sys.executable, '-m', 'ai_agent.cli', 'assess', '--help'], capture_output=True, text=True)
        for flag in ('--provider', '--model', '--base-url', '--api-key'):
            self.assertNotIn(flag, result.stdout)

    def test_full_agent_demo_and_eval_with_network_disabled(self):
        script = '''
import importlib.abc, socket, sys
class DenyNetworkAndLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in ('openai', 'ollama', 'requests', 'httpx', 'c8lab', 'python'):
            raise AssertionError('External dependency forbidden')
sys.meta_path.insert(0, DenyNetworkAndLegacy())
def denied(*args, **kwargs): raise AssertionError('Network forbidden')
class DisabledSocket(socket.socket):
    def __new__(cls, *args, **kwargs): return denied()
socket.socket = DisabledSocket
socket.create_connection = denied
socket.getaddrinfo = denied
from ai_agent.cli import main
from ai_agent.evaluation import evaluate
from ai_agent.agent_loop import LocalAgent
from ai_agent.logging_utils import audit_record
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
assert LocalAgent().assess('Pay Alice 0.05 CC for coffee').action.value == 'PROCEED_TO_DAML'
for answer in ('yes', 'no', ''):
    with patch('builtins.input', return_value=answer), redirect_stdout(StringIO()) as out:
        assert main(['run-agent', '--source', 'demo']) == 0
    assert 'WOULD_SUBMIT' in out.getvalue()
with patch('builtins.input', side_effect=['Pay Alice 0.05 CC', '']), redirect_stdout(StringIO()):
    assert main(['run-agent', '--source', 'stdin']) == 0
r = evaluate()
assert r['unsafe_proceed_rate'] == 0
assert all(x['correct'] and x['risk_flags_match'] for x in r['results'])
record = audit_record(LocalAgent().assess('Pay Alice 0.05 CC for coffee'))
assert 'recent_transactions' not in record and 'history' not in record
assert not ({'openai', 'ollama', 'c8lab'} & sys.modules.keys())
print('network-blocked local assessment, demo, stdin and evaluation passed')
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reference_generation_does_not_read_evaluation(self):
        source = Path('ai_agent/anomaly.py').read_text()
        self.assertNotIn('scenarios.json', source)
        self.assertNotIn('SCENARIOS_PATH', source)
        self.assertNotIn('pickle', source)
