from dataclasses import dataclass
from .models import Action, AgentDecision, RiskSignals, SEVERITY
from .policy import WalletPolicy


@dataclass(frozen=True)
class GuardrailResult:
    action: Action
    rule_action: Action
    reasons: tuple[str, ...]
    policy_references: tuple[str, ...]


def validate(decision: AgentDecision, risk: RiskSignals, policy: WalletPolicy) -> GuardrailResult:
    hard = {'insufficient_balance': 'supported_currency', 'blocked_category': 'blocked_categories',
            'exceeds_hard_maximum': 'hard_preflight_maximum', 'exceeds_balance_fraction': 'maximum_balance_fraction'}
    review = {'exceeds_daily_budget': 'daily_budget', 'exceeds_ai_review_threshold': 'ai_review_threshold'}
    reasons = [key for key in hard if getattr(risk, key)]
    refs = ['policy.' + hard[k] for k in reasons]
    rule = Action.BLOCK_PRE_LEDGER if reasons else Action.PROCEED_TO_DAML
    for key, ref in review.items():
        if getattr(risk, key):
            reasons.append(key)
            refs.append('policy.' + ref)
    for condition, reason, ref in (
        (risk.new_recipient and policy.new_recipient_requires_review, 'new_recipient', 'new_recipient_requires_review'),
        (risk.anomaly_score >= policy.anomaly_review_threshold, 'anomaly_score', 'anomaly_review_threshold'),
        (decision.confidence < policy.low_confidence_threshold, 'low_confidence', 'low_confidence_threshold')):
        if condition:
            reasons.append(reason)
            refs.append('policy.' + ref)
    if reasons and rule != Action.BLOCK_PRE_LEDGER:
        rule = Action.REQUIRE_HUMAN_CONFIRMATION
    return GuardrailResult(max((decision.action, rule), key=SEVERITY.get), rule, tuple(reasons), tuple(refs))
