"""Explicit execution controller, kept outside the agent/tool namespace."""
from dataclasses import dataclass
from typing import Protocol
from .models import Action, PaymentIntent, ValidationError
from .orchestrator import Assessment
from .memory import WalletContextProvider
from .policy import WalletPolicy
from .risk import calculate_risk
from .guardrail import validate


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    detail: str
    mock: bool


class PaymentExecutionAdapter(Protocol):
    def submit(self, intent: PaymentIntent) -> ExecutionResult: ...


class MockPaymentExecutionAdapter:
    def __init__(self):
        self.records: list[PaymentIntent] = []

    def submit(self, intent: PaymentIntent) -> ExecutionResult:
        self.records.append(intent)
        return ExecutionResult('WOULD_SUBMIT', 'Would submit to existing Daml Mandate; no Canton Coin moved', True)


class ExecutionController:
    """Trusted application API, not an LLM tool. Refresh preflight before handoff.

    A human yes authorizes this exact in-memory assessment only. It cannot
    override hard rules. Live adapters additionally require their own opt-in.
    """
    def __init__(self, adapter: PaymentExecutionAdapter, context: WalletContextProvider, policy: WalletPolicy):
        self.adapter, self.context, self.policy = adapter, context, policy
        self._used: list[Assessment] = []

    def execute(self, assessment: Assessment, human_decision: bool | None = None) -> ExecutionResult:
        if human_decision is not None and type(human_decision) is not bool:
            raise ValidationError('Human decision must be explicit boolean')
        if any(a is assessment for a in self._used):
            return ExecutionResult('ALREADY_HANDLED', 'Assessment already handled', True)
        if assessment.intent is None or assessment.action == Action.BLOCK_PRE_LEDGER:
            return ExecutionResult('BLOCKED', 'No execution permitted', True)
        fresh = validate(assessment.recommendation,
                         calculate_risk(assessment.intent, self.context.snapshot(), self.policy), self.policy)
        if fresh.action == Action.BLOCK_PRE_LEDGER:
            return ExecutionResult('BLOCKED', 'Fresh preflight blocked execution', True)
        review = Action.REQUIRE_HUMAN_CONFIRMATION in (assessment.action, fresh.action)
        if human_decision is False:
            self._used.append(assessment)
            return ExecutionResult('DECLINED', 'Human declined; no submission', True)
        if review and human_decision is not True:
            return ExecutionResult('AWAITING_HUMAN', 'Explicit yes/no required for this payment', True)
        # Consume before submission: an ambiguous remote error must not auto-retry.
        self._used.append(assessment)
        return self.adapter.submit(assessment.intent)
