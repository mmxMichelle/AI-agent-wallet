from decimal import Decimal as D
import re
from .models import PaymentIntent, WalletContext, RiskSignals
from .policy import WalletPolicy


def calculate_risk(intent: PaymentIntent, context: WalletContext, policy: WalletPolicy) -> RiskSignals:
    amounts = [t.amount for t in context.recent_transactions if t.currency == intent.currency]
    recipient = [t.amount for t in context.recent_transactions
                 if t.recipient == intent.recipient and t.currency == intent.currency]
    avg = lambda xs: sum(xs, D('0')) / len(xs) if xs else None
    ra, oa = avg(recipient), avg(amounts)
    ratio = intent.amount / context.balance if context.balance else D('1')
    rr, overall = intent.amount / ra if ra else None, intent.amount / oa if oa else None
    trusted = intent.recipient in policy.trusted_recipients
    score = min(D('1'), (D('0.25') if not recipient and not trusted else D('0'))
                + (D('0.35') if ratio > D('0.5') else D('0'))
                + (D('0.4') if max(rr or D('0'), overall or D('0')) > 3 else D('0')))
    # Category labels from a model are not authoritative: also inspect literal purpose terms.
    words = set(re.findall(r'\w+', intent.purpose.lower()))
    blocked = bool(words & set(policy.blocked_categories)) or (intent.category or '').lower() in policy.blocked_categories
    return RiskSignals(ratio, not recipient, trusted, len(recipient), ra, oa, rr, overall,
                       context.daily_spend + intent.amount > policy.daily_budget,
                       intent.amount >= policy.ai_review_threshold,
                       ratio > policy.maximum_balance_fraction,
                       intent.amount > policy.hard_preflight_maximum,
                       blocked, intent.amount > context.balance, score)
