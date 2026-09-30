"""Auditable, explicit lifecycle. Invalid transitions never silently succeed."""
from dataclasses import dataclass, field
from enum import Enum
from .models import ValidationError


class State(str, Enum):
    RECEIVED = 'RECEIVED'
    VALIDATING = 'VALIDATING'
    GATHERING_CONTEXT = 'GATHERING_CONTEXT'
    BUILDING_FEATURES = 'BUILDING_FEATURES'
    ASSESSING_ANOMALY = 'ASSESSING_ANOMALY'
    ASSESSING_RISK = 'ASSESSING_RISK'
    PLANNING = 'PLANNING'
    WAITING_FOR_HUMAN = 'WAITING_FOR_HUMAN'
    READY_FOR_EXECUTION = 'READY_FOR_EXECUTION'
    EXECUTING = 'EXECUTING'
    BLOCKED = 'BLOCKED'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'


EDGES = {
    State.RECEIVED: {State.VALIDATING},
    State.VALIDATING: {State.GATHERING_CONTEXT, State.BLOCKED},
    State.GATHERING_CONTEXT: {State.BUILDING_FEATURES, State.ASSESSING_RISK},
    State.BUILDING_FEATURES: {State.ASSESSING_ANOMALY},
    State.ASSESSING_ANOMALY: {State.ASSESSING_RISK},
    State.ASSESSING_RISK: {State.PLANNING},
    State.PLANNING: {State.BLOCKED, State.WAITING_FOR_HUMAN, State.READY_FOR_EXECUTION},
    State.WAITING_FOR_HUMAN: {State.READY_FOR_EXECUTION, State.COMPLETED, State.BLOCKED},
    State.READY_FOR_EXECUTION: {State.EXECUTING, State.BLOCKED},
    State.EXECUTING: {State.COMPLETED, State.BLOCKED, State.WAITING_FOR_HUMAN},
    State.BLOCKED: {State.COMPLETED},
    State.FAILED: {State.COMPLETED},
    State.COMPLETED: set(),
}


@dataclass
class StateMachine:
    state: State = State.RECEIVED
    history: list[dict] = field(default_factory=list)

    def transition(self, target: State, action: str, reason: str):
        if target not in EDGES[self.state] and not (target == State.FAILED and self.state not in (State.COMPLETED, State.FAILED)):
            raise ValidationError('Illegal agent state transition')
        self.history.append({'from': self.state.value, 'to': target.value, 'action': action, 'reason': reason})
        self.state = target
