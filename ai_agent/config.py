from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / 'config' / 'wallet_policy.json'
HISTORY_PATH = ROOT / 'data' / 'demo_history.json'
SCENARIOS_PATH = ROOT / 'eval' / 'scenarios.json'
