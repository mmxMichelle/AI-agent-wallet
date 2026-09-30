"""Strict, immutable domain objects. Monetary JSON values must be strings."""
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import json


class ValidationError(ValueError):
    pass


class Action(str, Enum):
    PROCEED_TO_DAML = 'PROCEED_TO_DAML'
    REQUIRE_HUMAN_CONFIRMATION = 'REQUIRE_HUMAN_CONFIRMATION'
    BLOCK_PRE_LEDGER = 'BLOCK_PRE_LEDGER'


SEVERITY = {a: n for n, a in enumerate(Action)}


def decimal(value: object) -> Decimal:
    if not isinstance(value, (str, Decimal)):
        raise ValidationError('Decimal values must be strings or Decimal, never float')
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValidationError('Invalid decimal') from None
    if not result.is_finite() or abs(result) > Decimal('1e18') or result.as_tuple().exponent < -18:
        raise ValidationError('Non-finite or out-of-range decimal')
    return result


def strict_json(raw: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValidationError('Duplicate JSON key')
            result[key] = value
        return result
    try:
        result = json.loads(raw, object_pairs_hook=pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValidationError('Invalid constant')))
    except (ValueError, TypeError):
        raise ValidationError('Expected strict JSON object') from None
    if not isinstance(result, dict):
        raise ValidationError('Expected JSON object')
    return result


def text_value(value: object, name: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 2000 or (not allow_empty and not value.strip()):
        raise ValidationError(f'Invalid {name}')
    return value.strip()


@dataclass(frozen=True)
class PaymentIntent:
    recipient: str
    amount: Decimal
    currency: str
    purpose: str
    category: str | None = None

    def __post_init__(self):
        object.__setattr__(self, 'recipient', text_value(self.recipient, 'recipient'))
        object.__setattr__(self, 'amount', decimal(self.amount))
        text_value(self.purpose, 'purpose', True)
        if self.amount <= 0 or self.currency != 'CC':
            raise ValidationError('Positive amount and supported currency CC required')
        if self.category is not None:
            text_value(self.category, 'category')
        if any(x in self.recipient.lower() for x in (' or ', ' and ', ',', '?')):
            raise ValidationError('Ambiguous recipient; specify one recipient')

    @classmethod
    def from_dict(cls, value: dict):
        if not isinstance(value, dict) or set(value) - {'recipient', 'amount', 'currency', 'purpose', 'category'}:
            raise ValidationError('Unexpected intent fields')
        if not {'recipient', 'amount', 'currency', 'purpose'} <= set(value):
            raise ValidationError('Missing required intent fields')
        return cls(**value)


@dataclass(frozen=True)
class Transaction:
    recipient: str
    amount: Decimal
    currency: str
    purpose: str
    category: str | None
    timestamp: str
    final_decision: str
    human_review: bool

    def __post_init__(self):
        PaymentIntent(self.recipient, self.amount, self.currency, self.purpose, self.category)
        object.__setattr__(self, 'amount', decimal(self.amount))


@dataclass(frozen=True)
class WalletContext:
    balance: Decimal
    daily_spend: Decimal
    recent_transactions: tuple[Transaction, ...] = ()

    def __post_init__(self):
        for name in ('balance', 'daily_spend'):
            value = decimal(getattr(self, name))
            if value < 0:
                raise ValidationError('Negative wallet context')
            object.__setattr__(self, name, value)
        object.__setattr__(self, 'recent_transactions', tuple(self.recent_transactions))


@dataclass(frozen=True)
class RiskSignals:
    amount_to_balance_ratio: Decimal
    new_recipient: bool
    trusted_recipient: bool
    recipient_transaction_count: int
    recipient_average_amount: Decimal | None
    overall_average_amount: Decimal | None
    amount_vs_recipient_average: Decimal | None
    amount_vs_overall_average: Decimal | None
    exceeds_daily_budget: bool
    exceeds_ai_review_threshold: bool
    exceeds_balance_fraction: bool
    exceeds_hard_maximum: bool
    blocked_category: bool
    insufficient_balance: bool
    anomaly_score: Decimal


@dataclass(frozen=True)
class AgentDecision:
    action: Action
    confidence: Decimal
    reasons: tuple[str, ...]
    policy_references: tuple[str, ...] = ()

    def __post_init__(self):
        try:
            object.__setattr__(self, 'action', Action(self.action))
        except (ValueError, TypeError):
            raise ValidationError('Unknown action') from None
        confidence = decimal(self.confidence)
        if not 0 <= confidence <= 1:
            raise ValidationError('Confidence outside [0, 1]')
        object.__setattr__(self, 'confidence', confidence)
        for name in ('reasons', 'policy_references'):
            values = getattr(self, name)
            if not isinstance(values, (list, tuple)) or len(values) > 20:
                raise ValidationError('Expected bounded list of public strings')
            for value in values:
                text_value(value, name)
            object.__setattr__(self, name, tuple(values))


def jsonable(value):
    if is_dataclass(value):
        return {f.name: jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (Decimal, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value
