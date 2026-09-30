"""Ordered local numerical features; floats are used only for ML, never spending."""
from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal
import math
from .models import PaymentIntent, WalletContext, ValidationError
from .policy import WalletPolicy


@dataclass(frozen=True)
class TransactionFeatures:
    amount: float
    amount_to_balance_ratio: float
    recipient_transaction_count: float
    recipient_frequency: float
    recipient_average_amount: float
    amount_vs_recipient_average: float
    overall_average_amount: float
    amount_vs_overall_average: float
    daily_spend: float
    daily_spend_ratio: float
    new_recipient: float
    trusted_recipient: float
    time_since_last_recipient_payment: float
    recipient_time_missing: float

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                raise ValidationError('Invalid numerical feature')
        for name in ('recipient_frequency', 'new_recipient', 'trusted_recipient', 'recipient_time_missing'):
            if getattr(self, name) > 1:
                raise ValidationError('Feature fraction outside [0, 1]')

    @classmethod
    def names(cls):
        return tuple(f.name for f in fields(cls))

    def vector(self):
        return tuple(float(getattr(self, name)) for name in self.names())


def build_features(intent: PaymentIntent, context: WalletContext, policy: WalletPolicy, *, observed_at=None):
    history = [t for t in context.recent_transactions if t.currency == intent.currency]
    recipient = [t for t in history if t.recipient == intent.recipient]
    average = lambda rows: sum((t.amount for t in rows), Decimal('0')) / len(rows) if rows else Decimal('0')
    ra, oa = average(recipient), average(history)
    elapsed, missing = 0.0, 1.0
    if observed_at is not None and recipient:
        try:
            now = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
            dates = [datetime.fromisoformat(t.timestamp.replace('Z', '+00:00')) for t in recipient]
            if now.tzinfo is None or any(t.tzinfo is None or t > now for t in dates):
                raise ValueError()
            elapsed, missing = (now - max(dates)).total_seconds(), 0.0
        except (ValueError, TypeError, AttributeError):
            raise ValidationError('Invalid observation/history timestamp') from None
    values = (intent.amount, intent.amount / context.balance if context.balance else Decimal('1'),
              len(recipient), len(recipient) / len(history) if history else 0,
              ra, intent.amount / ra if ra else 0, oa, intent.amount / oa if oa else 0,
              context.daily_spend, (context.daily_spend + intent.amount) / policy.daily_budget,
              int(not recipient), int(intent.recipient in policy.trusted_recipients), elapsed, missing)
    return TransactionFeatures(*(float(v) for v in values))
