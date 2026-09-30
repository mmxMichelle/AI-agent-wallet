import subprocess
import sys
import unittest
from ai_agent.config import ROOT


class BoundaryTests(unittest.TestCase):
    def test_existing_offline_demo_workflow(self):
        script = '''
import sys
from decimal import Decimal
from unittest.mock import patch
sys.path.insert(0, 'python')
import demo_ui
with patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden')):
    state = demo_ui.DemoState(offline_demo=True)
    state.agent_balance, state.vendor_balance = Decimal('5'), Decimal('0')
    state.approval_threshold = Decimal('0.2')
    assert state.create_demo_mandate()['ok']
    assert state.request_payment({'amount': '0.1'})['ok']
    assert state.agent_balance == Decimal('4.9')
    assert state.request_payment({'amount': '0.5'})['ok']
    assert state.agent_balance == Decimal('4.9')
    assert state.approve_payment()['ok']
    assert state.agent_balance == Decimal('4.4')
    assert state.request_payment({'amount': '0.5'})['ok']
    assert state.reject_payment()['ok']
    assert state.agent_balance == Decimal('4.4')
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_offline_with_network_and_legacy_imports_forbidden(self):
        script = '''
import sys, importlib.abc, socket
class DenyLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'c8lab' or fullname == 'python' or fullname.startswith('python.') or fullname in ('mandate_client', 'demo_ui'):
            raise AssertionError('Legacy import: ' + fullname)
sys.meta_path.insert(0, DenyLegacy())
def denied(*args, **kwargs):
    raise AssertionError('Network forbidden')
class DisabledSocket(socket.socket):
    def __new__(cls, *args, **kwargs):
        return denied()
socket.socket = DisabledSocket
socket.create_connection = denied
import ai_agent.legacy_adapter
from ai_agent.orchestrator import GovernedAgent
from ai_agent.evaluation import evaluate
from ai_agent.ledger import ExecutionController, MockPaymentExecutionAdapter
a = GovernedAgent()
r = a.assess('Pay Alice 0.05 CC for coffee')
assert ExecutionController(MockPaymentExecutionAdapter(), a.context, a.policy).execute(r).mock
assert evaluate()['unsafe_proceed_rate'] == 0
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
from ai_agent.cli import main
with patch('ai_agent.legacy_adapter.LegacyDamlPaymentExecutionAdapter.submit', side_effect=denied):
    for request, answer in [('Pay Charlie 0.6 CC for dinner', 'yes'),
                            ('Pay Charlie 0.6 CC for dinner', 'no'),
                            ('Pay Alice 0.05 CC for coffee', 'yes'),
                            ('Pay UnknownXYZ 0.9 CC for dinner', 'yes')]:
        with patch('builtins.input', return_value=answer), redirect_stdout(StringIO()):
            assert main(['assess', request, '--interactive']) == 0
assert 'c8lab' not in sys.modules
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_frozen_legacy_files_match_baseline(self):
        paths = ['c8lab.py', 'python', 'daml-starter']
        result = subprocess.run(['git', 'diff', '--exit-code', 'backup/pre-ai-agent-baseline', '--', *paths],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
