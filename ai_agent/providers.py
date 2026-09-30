"""No vendor SDK. Remote inference is an explicit, separate opt-in."""
import ipaddress
import json
import os
import re
from typing import Protocol
from urllib import request
from urllib.parse import urlparse
from .models import strict_json


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


SUPPORTED_PROVIDERS = ('mock', 'openai-compatible', 'ollama')
PROVIDER_HELP = """Available provider modes:

mock
  Offline deterministic provider; no API key; no network; default
openai-compatible
  User-supplied API endpoint/model/key; network may be required
  Loopback endpoints (e.g. LM Studio) may omit the key
ollama
  User-run local model; no API key; local Ollama server required
"""


def _setting(value, name, default=''):
    return value if value is not None else os.environ.get(name, default)


def _endpoint(base):
    """Permit plain HTTP only on explicit loopback hosts; never echo config."""
    try:
        parsed = urlparse(base)
        host = parsed.hostname
        local = host == 'localhost'
        if host and not local:
            try:
                local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                pass
        if (not host or not parsed.netloc or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or any(c.isspace() or ord(c) < 32 for c in base)
                or parsed.scheme not in ('http', 'https')
                or (parsed.scheme == 'http' and not local)):
            raise ValueError()
        # Accessing port also validates its syntax/range.
        parsed.port
        return local
    except (ValueError, TypeError):
        raise ProviderError('Invalid LLM endpoint: HTTPS required except on loopback; '
                            'credentials/query/fragment are forbidden. No payment action was taken.') from None


def _http_transport(req, *, timeout, limit):
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    # Ignore ambient proxies so credentials go only to the selected endpoint.
    with request.build_opener(request.ProxyHandler({}), NoRedirect).open(req, timeout=timeout) as response:
        return response.read(limit)


class _HTTPProvider:
    """Shared bounded transport and normalized, untrusted JSON-text response."""
    label = 'LLM'

    def _complete(self, messages, path, payload):
        try:
            # Tool observations are data, never executable vendor tool definitions.
            wire = [dict(role='user' if m['role'] == 'tool' else m['role'], content=m['content'])
                    for m in messages]
            body = json.dumps(dict(payload, model=self.model, messages=wire)).encode()
            headers = {'Content-Type': 'application/json'}
            if self.key:
                headers['Authorization'] = 'Bearer ' + self.key
            req = request.Request(self.base.rstrip('/') + path, data=body, headers=headers)
            raw = self.transport(req, timeout=20, limit=65537)
        except Exception:
            # Neither HTTP bodies, URLs, credentials nor underlying exceptions escape.
            raise ProviderError('Unable to connect to the configured ' + self.label +
                                ' endpoint or complete its request. No payment action was taken.') from None
        try:
            if not isinstance(raw, bytes) or len(raw) > 65536:
                raise ValueError()
            # A server may echo authentication material. Reject it before any audit path.
            if self.key and self.key in raw.decode('utf-8'):
                raise ValueError()
            envelope = strict_json(raw)
            content = self._content(envelope)
            if not isinstance(content, str) or len(content) > 10000:
                raise ValueError()
            if self.key and self.key in content:
                raise ValueError()
            normalized = strict_json(content)
            if self.key and self.key in json.dumps(normalized, ensure_ascii=False):
                raise ValueError()
            return content
        except Exception:
            raise ProviderError('Provider response could not be safely parsed. '
                                'Escalating/blocking according to the existing safety policy.') from None


class OpenAICompatibleProvider(_HTTPProvider):
    """Generic chat-completions API. No vendor SDK or default hosted endpoint/model."""
    label = 'OpenAI-compatible'

    def __init__(self, model=None, base_url=None, *, transport=None):
        self.base = _setting(base_url, 'LLM_BASE_URL')
        self.model = _setting(model, 'LLM_MODEL')
        self.key = os.environ.get('LLM_API_KEY', '')
        if not self.base or not self.model:
            raise ProviderError('LLM_BASE_URL and LLM_MODEL are required; use offline/mock mode '
                                'for offline inference. No payment action was taken.')
        local = _endpoint(self.base)
        if not local and not self.key:
            raise ProviderError('LLM_API_KEY is required for the selected remote provider. '
                                'No payment action was taken.')
        self.transport = transport if transport is not None else _http_transport

    def complete(self, messages: list[dict[str, str]]) -> str:
        return self._complete(messages, '/chat/completions',
                              {'temperature': 0, 'stream': False,
                               'response_format': {'type': 'json_object'}})

    def _content(self, envelope):
        choice = envelope['choices'][0]
        message = choice['message']
        if (choice.get('finish_reason') not in (None, 'stop')
                or message.get('tool_calls') or message.get('function_call')
                or message.get('refusal')):
            raise ValueError()
        return message['content']


class OllamaProvider(_HTTPProvider):
    """Explicit user-run Ollama; never starts a server or downloads models."""
    label = 'Ollama'

    def __init__(self, model=None, base_url=None, *, transport=None):
        self.base = _setting(base_url, 'OLLAMA_BASE_URL', 'http://localhost:11434')
        self.model = _setting(model, 'OLLAMA_MODEL')
        self.key = ''  # Never forward an unrelated hosted-provider credential.
        _endpoint(self.base)
        if not self.model:
            raise ProviderError('OLLAMA_MODEL or --model is required. No payment action was taken.')
        self.transport = transport if transport is not None else _http_transport

    def complete(self, messages: list[dict[str, str]]) -> str:
        return self._complete(messages, '/api/chat',
                              {'stream': False, 'format': 'json', 'options': {'temperature': 0}})

    def _content(self, envelope):
        if (envelope.get('done') is not True or envelope['message'].get('tool_calls')
                or envelope.get('done_reason') not in (None, 'stop')):
            raise ValueError()
        return envelope['message']['content']


def create_provider(provider_name=None, model=None, base_url=None, *, transport=None) -> LLMProvider:
    """CLI arguments > environment > safe defaults. Credentials are environment-only.

    Endpoint/model/key presence never selects a provider. Evaluation and direct
    GovernedAgent construction retain their deterministic mock defaults.
    """
    name = _setting(provider_name, 'LLM_PROVIDER', 'mock')
    if name == 'mock':
        return MockLLMProvider()
    if name == 'openai-compatible':
        return OpenAICompatibleProvider(model, base_url, transport=transport)
    if name == 'ollama':
        return OllamaProvider(model, base_url, transport=transport)
    raise ProviderError('Unknown LLM provider. Supported providers: ' +
                        ', '.join(SUPPORTED_PROVIDERS) + '. No payment action was taken.')
