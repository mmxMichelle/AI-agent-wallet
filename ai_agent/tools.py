from dataclasses import dataclass
from .models import PaymentIntent, WalletContext, ValidationError, jsonable
from .policy import WalletPolicy
TOOL_NAMES = ('get_balance', 'get_transaction_history', 'get_recipient_history',
              'retrieve_wallet_policy', 'calculate_risk_signals')
from .retrieval import retrieve
from .risk import calculate_risk


@dataclass(frozen=True)
class ToolRequest:
    name: str
    arguments: dict

    @classmethod
    def from_dict(cls, data: dict):
        if set(data) != {'type', 'name', 'arguments'} or data['type'] != 'tool':
            raise ValidationError('Invalid tool request schema')
        if not isinstance(data['name'], str) or data['name'] not in TOOL_NAMES or data['arguments'] != {}:
            raise ValidationError('Tool not allowed or arguments invalid')
        return cls(data['name'], {})


class ReadOnlyTools:
    """All tools are bound to one trusted snapshot and one validated intent.

    No caller-supplied paths, recipients, amounts or policy overrides are accepted.
    """
    names = TOOL_NAMES

    def __init__(self, intent: PaymentIntent, context: WalletContext, policy: WalletPolicy):
        self.intent, self.context, self.policy = intent, context, policy

    def invoke(self, tool: ToolRequest):
        ToolRequest.from_dict({'type': 'tool', 'name': tool.name, 'arguments': tool.arguments})
        i, c, p = self.intent, self.context, self.policy
        registry = {
            'get_balance': lambda: {'balance': c.balance, 'daily_spend': c.daily_spend, 'currency': 'CC'},
            'get_transaction_history': lambda: c.recent_transactions,
            'get_recipient_history': lambda: tuple(t for t in c.recent_transactions if t.recipient == i.recipient),
            'retrieve_wallet_policy': lambda: retrieve(p, f'{i.recipient} {i.purpose} amount balance daily budget recipient'),
            'calculate_risk_signals': lambda: calculate_risk(i, c, p),
        }
        return jsonable(registry[tool.name]())
