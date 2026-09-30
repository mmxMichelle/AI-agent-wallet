"""No vendor SDK. Remote inference is an explicit, separate opt-in."""
import json
import os
import re
from typing import Protocol
from urllib import request, error
from urllib.parse import urlparse
from .models import ValidationError


class ProviderError(RuntimeError):
    pass


class LLMProvider(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str: ...


TOOL_NAMES = ('get_balance', 'get_transaction_history', 'get_recipient_history',
              'retrieve_wallet_policy', 'calculate_risk_signals')


class MockLLMProvider:
    """Deterministic limited grammar plus a scripted read-only tool plan.

    This is a test double, not a trained language model. Scripts are consumed in
    order; exhaustion fails closed. Default recommendations use observed risks.
    """
    def __init__(self, responses: list[str] | None = None):
        self.responses = iter(responses) if responses is not None else None

    def complete(self, messages: list[dict[str, str]]) -> str:
        if self.responses is not None:
            try:
                return next(self.responses)
            except StopIteration:
                raise ProviderError('Script exhausted') from None
        if messages[0]['content'].startswith('INTENT'):
            raw = json.loads(messages[-1]['content'])['request']
            match = re.fullmatch(r'(?:Pay|Send)\s+(.+?)\s+([+-]?\d+(?:\.\d+)?)\s+([A-Za-z]+)(?:\s+for\s+(.+))?', raw, re.I)
            if not match:
                return json.dumps({'error': 'Specify one recipient, explicit amount, and currency: Pay Alice 0.05 CC for coffee'})
            recipient, amount, currency, purpose = match.groups()
            return json.dumps(dict(recipient=recipient, amount=amount, currency=currency.upper(), purpose=purpose or ''))
        observed = [json.loads(m['content']) for m in messages if m['role'] == 'tool']
        used = {v['name'] for v in observed}
        for name in TOOL_NAMES:
            if name not in used:
                return json.dumps({'type': 'tool', 'name': name, 'arguments': {}})
        risk = next(v['result'] for v in observed if v['name'] == 'calculate_risk_signals')
        action = 'PROCEED_TO_DAML'
        reasons = ['Observed context is within demo thresholds']
        if any(risk[k] for k in ('new_recipient', 'exceeds_daily_budget', 'exceeds_ai_review_threshold')):
            action, reasons = 'REQUIRE_HUMAN_CONFIRMATION', ['Context warrants human review']
        if any(risk[k] for k in ('insufficient_balance', 'blocked_category', 'exceeds_hard_maximum', 'exceeds_balance_fraction')):
            action, reasons = 'BLOCK_PRE_LEDGER', ['Observed context breaches a hard preflight rule']
        return json.dumps({'type': 'decision', 'action': action, 'confidence': '0.95',
                           'reasons': reasons, 'policy_references': []})


class OpenAICompatibleProvider:
    """Optional chat-completions transport, with no redirects or credential logging."""
    def __init__(self):
        self.base = os.environ.get('LLM_BASE_URL', '')
        self.key = os.environ.get('LLM_API_KEY', '')
        self.model = os.environ.get('LLM_MODEL', '')
        parsed = urlparse(self.base)
        if not all((self.base, self.key, self.model)):
            raise ProviderError('Missing LLM configuration; use offline/mock mode')
        if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
            raise ProviderError('LLM_BASE_URL must be an HTTPS endpoint without credentials/query')

    def complete(self, messages: list[dict[str, str]]) -> str:
        # Tool observations are data messages; no executable vendor tool definitions.
        wire = [dict(role='user' if m['role'] == 'tool' else m['role'], content=m['content']) for m in messages]
        body = json.dumps({'model': self.model, 'messages': wire, 'temperature': 0,
                           'response_format': {'type': 'json_object'}}).encode()
        req = request.Request(self.base.rstrip('/') + '/chat/completions', data=body,
                              headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        class NoRedirect(request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            with request.build_opener(NoRedirect).open(req, timeout=20) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise ProviderError('Provider response too large')
            content = json.loads(raw)['choices'][0]['message']['content']
            if not isinstance(content, str):
                raise ProviderError('Invalid provider response')
            return content
        except (error.URLError, OSError, ValueError, KeyError, IndexError, TypeError):
            raise ProviderError('LLM request failed; use offline/mock mode') from None
