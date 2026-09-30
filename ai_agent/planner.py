"""Missing-observation planning, independent of tools, ML and execution authority."""
from enum import Enum
from .models import Action, AgentDecision


class Step(str, Enum):
    VALIDATE_INTENT = 'VALIDATE_INTENT'
    FETCH_BALANCE = 'FETCH_BALANCE'
    LOAD_POLICY = 'LOAD_POLICY'
    FETCH_RECIPIENT_HISTORY = 'FETCH_RECIPIENT_HISTORY'
    FETCH_TRANSACTION_HISTORY = 'FETCH_TRANSACTION_HISTORY'
    BUILD_FEATURES = 'BUILD_FEATURES'
    RUN_ANOMALY_MODEL = 'RUN_ANOMALY_MODEL'
    ASSESS_RISK = 'ASSESS_RISK'
    PLAN = 'PLAN'
    REQUIRE_HUMAN = 'REQUIRE_HUMAN'
    BLOCK = 'BLOCK'
    EXECUTE = 'EXECUTE'
    COMPLETE = 'COMPLETE'


class AutonomousPlanner:
    def next_step(self, observations):
        if 'intent' not in observations:
            return Step.VALIDATE_INTENT
        if observations.get('invalid_intent'):
            return Step.BLOCK
        for key, action in (('balance', Step.FETCH_BALANCE), ('policy', Step.LOAD_POLICY)):
            if key not in observations:
                return action
        if observations.get('hard_block'):
            return Step.ASSESS_RISK if 'risk' not in observations else Step.PLAN if 'guardrail' not in observations else Step.BLOCK
        for key, action in (('recipient_history', Step.FETCH_RECIPIENT_HISTORY),
                            ('history', Step.FETCH_TRANSACTION_HISTORY), ('features', Step.BUILD_FEATURES),
                            ('anomaly_score', Step.RUN_ANOMALY_MODEL), ('risk', Step.ASSESS_RISK),
                            ('guardrail', Step.PLAN)):
            if key not in observations:
                return action
        return {Action.BLOCK_PRE_LEDGER: Step.BLOCK, Action.REQUIRE_HUMAN_CONFIRMATION: Step.REQUIRE_HUMAN,
                Action.PROCEED_TO_DAML: Step.EXECUTE}[observations['guardrail'].action]

    def recommend(self, risk, policy):
        # Conservative local proposal; mandatory guardrail independently decides.
        if any((risk.insufficient_balance, risk.blocked_category, risk.exceeds_hard_maximum, risk.exceeds_balance_fraction)):
            action = Action.BLOCK_PRE_LEDGER
        elif risk.anomaly_score >= policy.anomaly_review_threshold:
            action = Action.REQUIRE_HUMAN_CONFIRMATION
        else:
            action = Action.PROCEED_TO_DAML
        return AgentDecision(action, '1', ('Local observations evaluated',))
