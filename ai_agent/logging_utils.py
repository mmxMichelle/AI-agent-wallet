"""Allowlisted audit fields. Never serialize credentials or raw context histories."""
from datetime import datetime, timezone
from uuid import uuid4
from .models import jsonable
from .orchestrator import Assessment
from .ledger import ExecutionResult


def audit_record(assessment: Assessment, execution: ExecutionResult | None = None,
                 human_decision: bool | None = None) -> dict:
    return jsonable({
        'request_id': str(uuid4()), 'timestamp': datetime.now(timezone.utc).isoformat(),
        'parsed_intent': assessment.intent, 'tools_invoked': assessment.tools_invoked,
        'agent_state': assessment.state, 'agent_state_transitions': assessment.transitions,
        'agent_observations': assessment.observations, 'features': assessment.features,
        'anomaly_score': assessment.local_anomaly_score, 'planner_action': assessment.planner_action,
        'guardrail_action': assessment.guardrail.action,
        'policy_references': sorted(set(assessment.guardrail.policy_references)
                                    | set(assessment.recommendation.policy_references)
                                    | {e['reference'] for e in assessment.policy_excerpts}),
        'risk_signals': assessment.risk, 'ai_recommendation': assessment.recommendation.action,
        'ai_confidence': assessment.recommendation.confidence,
        'public_reasons': assessment.guardrail.reasons,
        'deterministic_guardrail_action': assessment.guardrail.rule_action,
        'final_action': assessment.action, 'human_decision': human_decision,
        'execution_result': execution,
        'error': assessment.error,
    })
