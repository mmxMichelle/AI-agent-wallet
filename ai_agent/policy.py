from dataclasses import dataclass
from decimal import Decimal
from .config import POLICY_PATH
from .models import ValidationError, decimal, strict_json


@dataclass(frozen=True)
class WalletPolicy:
    label: str
    supported_currency: str
    daily_budget: Decimal
    ai_review_threshold: Decimal
    hard_preflight_maximum: Decimal
    maximum_balance_fraction: Decimal
    new_recipient_requires_review: bool
    trusted_recipients: tuple[str, ...]
    blocked_categories: tuple[str, ...]
    anomaly_review_threshold: Decimal
    low_confidence_threshold: Decimal

    def __post_init__(self):
        for name in ('daily_budget', 'ai_review_threshold', 'hard_preflight_maximum',
                     'maximum_balance_fraction', 'anomaly_review_threshold', 'low_confidence_threshold'):
            value = decimal(getattr(self, name))
            if value <= 0:
                raise ValidationError('Policy thresholds must be positive')
            if name in ('maximum_balance_fraction', 'anomaly_review_threshold', 'low_confidence_threshold') and value > 1:
                raise ValidationError('Policy fraction exceeds one')
            object.__setattr__(self, name, value)
        if self.supported_currency != 'CC' or type(self.new_recipient_requires_review) is not bool:
            raise ValidationError('Invalid policy currency or review flag')
        for name in ('trusted_recipients', 'blocked_categories'):
            values = getattr(self, name)
            if not isinstance(values, (tuple, list)) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValidationError('Invalid policy list')
            object.__setattr__(self, name, tuple(values))


def load_policy(path=POLICY_PATH) -> WalletPolicy:
    try:
        return WalletPolicy(**strict_json(path.read_text()))
    except TypeError:
        raise ValidationError('Invalid policy schema') from None
