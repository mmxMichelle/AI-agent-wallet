"""Bounded observe-plan-act assessment plus separate guarded outcome handling."""
from dataclasses import dataclass, field, replace
from decimal import Decimal
from itertools import islice
from .anomaly import default_model
from .features import TransactionFeatures, build_features
from .guardrail import GuardrailResult, validate
from .memory import MockWalletContextProvider
from .models import Action, AgentDecision, PaymentIntent, RiskSignals, ValidationError
from .parser import parse_intent
from .planner import AutonomousPlanner, Step
from .policy import load_policy
from .risk import calculate_risk
from .state_machine import State, StateMachine
from .tools import ReadOnlyTools, ToolRequest


@dataclass(frozen=True)
class Assessment:
    intent: PaymentIntent | None
    risk: RiskSignals | None
    recommendation: AgentDecision
    guardrail: GuardrailResult
    tools_invoked: tuple[str, ...]
    policy_excerpts: tuple[dict, ...]
    error: str | None = None
    features: TransactionFeatures | None = None
    local_anomaly_score: Decimal | None = None
    state: State = State.RECEIVED
    transitions: tuple[dict, ...] = ()
    observations: tuple[dict, ...] = ()
    planner_action: str = ''

    @property
    def action(self):
        return self.guardrail.action


@dataclass
class Session:
    machine: StateMachine = field(default_factory=StateMachine)
    observed: dict = field(default_factory=dict)
    trace: list = field(default_factory=list)
    invoked: list = field(default_factory=list)
    tools: object = None
    snapshot: object = None
    selected: str = ''

    def move(self, state, step, reason):
        if state != self.machine.state:
            self.machine.transition(state, step.value, reason)


class LocalAgent:
    def __init__(self, context=None, policy=None, *, model=None, planner=None, max_steps=20):
        if type(max_steps) is not int or not 1 <= max_steps <= 100:
            raise ValidationError('max_steps must be between 1 and 100')
        self.context = context if context is not None else MockWalletContextProvider()
        self.policy = policy if policy is not None else load_policy()
        self.model = model if model is not None else default_model()
        self.planner = planner if planner is not None else AutonomousPlanner()
        self.max_steps = max_steps

    def assess(self, request):
        assessment, _ = self._assess(request)
        return assessment

    def _assess(self, request):
        session = Session()
        o = session.observed
        try:
            for _ in range(self.max_steps):
                step = self.planner.next_step(dict(o))
                if not isinstance(step, Step):
                    raise ValidationError('Planner action is not allowed')
                session.selected = step.value
                if step == Step.VALIDATE_INTENT:
                    session.move(State.VALIDATING, step, 'Validate explicit financial fields')
                    try:
                        o['intent'] = request if isinstance(request, PaymentIntent) else parse_intent(request)
                    except ValidationError:
                        o['intent'], o['invalid_intent'] = None, True
                    summary = 'Intent validated' if o['intent'] else 'CLARIFICATION_REQUIRED'
                elif step == Step.BLOCK and o.get('invalid_intent'):
                    session.move(State.BLOCKED, step, 'CLARIFICATION_REQUIRED')
                    return self._blocked(session, 'CLARIFICATION_REQUIRED', 'invalid_intent'), session
                elif step in (Step.FETCH_BALANCE, Step.LOAD_POLICY, Step.FETCH_RECIPIENT_HISTORY, Step.FETCH_TRANSACTION_HISTORY):
                    if not isinstance(o.get('intent'), PaymentIntent):
                        raise ValidationError('Validated intent required')
                    if session.tools is None:
                        session.snapshot = self.context.snapshot()
                        session.tools = ReadOnlyTools(o['intent'], session.snapshot, self.policy)
                    session.move(State.GATHERING_CONTEXT, step, 'Collect missing local observation')
                    name, key = {Step.FETCH_BALANCE: ('get_balance', 'balance'),
                                 Step.LOAD_POLICY: ('retrieve_wallet_policy', 'policy'),
                                 Step.FETCH_RECIPIENT_HISTORY: ('get_recipient_history', 'recipient_history'),
                                 Step.FETCH_TRANSACTION_HISTORY: ('get_transaction_history', 'history')}[step]
                    if key in o:
                        raise ValidationError('Planner repeated an observation')
                    o[key] = session.tools.invoke(ToolRequest(name, {}))
                    session.invoked.append(name)
                    if 'balance' in o and 'policy' in o:
                        early = calculate_risk(o['intent'], session.snapshot, self.policy)
                        o['hard_block'] = any((early.insufficient_balance, early.blocked_category,
                                               early.exceeds_hard_maximum, early.exceeds_balance_fraction))
                    summary = 'Local observation available: ' + key
                elif step == Step.BUILD_FEATURES:
                    if not {'balance', 'policy', 'history', 'recipient_history'} <= o.keys():
                        raise ValidationError('Missing context for features')
                    session.move(State.BUILDING_FEATURES, step, 'Build stable numerical vector')
                    o['features'] = build_features(o['intent'], session.snapshot, self.policy)
                    summary = '14 validated local features'
                elif step == Step.RUN_ANOMALY_MODEL:
                    session.move(State.ASSESSING_ANOMALY, step, 'Infer from local reference behaviour')
                    from .models import decimal
                    o['anomaly_score'] = decimal(self.model.score(o['features']))
                    if not 0 <= o['anomaly_score'] <= 1:
                        raise ValidationError('Invalid local anomaly score')
                    summary = 'Local behavioural anomaly score available'
                elif step == Step.ASSESS_RISK:
                    if not o.get('hard_block') and 'anomaly_score' not in o:
                        raise ValidationError('Missing anomaly assessment')
                    session.move(State.ASSESSING_RISK, step, 'Apply policy independently of ML')
                    # The allowlisted risk tool remains exercised; its deterministic result
                    # is independently combined with the validated learned score.
                    session.tools.invoke(ToolRequest('calculate_risk_signals', {}))
                    session.invoked.append('calculate_risk_signals')
                    o['risk'] = calculate_risk(o['intent'], session.snapshot, self.policy, o.get('anomaly_score'))
                    summary = 'Risk signals computed; hard rules cannot be relaxed'
                elif step == Step.PLAN:
                    session.move(State.PLANNING, step, 'Propose action then enforce mandatory guardrail')
                    o['decision'] = self.planner.recommend(o['risk'], self.policy)
                    if not isinstance(o['decision'], AgentDecision):
                        raise ValidationError('Invalid planner decision')
                    o['guardrail'] = validate(o['decision'], o['risk'], self.policy)
                    summary = 'Deterministic guardrail applied'
                elif step in (Step.BLOCK, Step.REQUIRE_HUMAN, Step.EXECUTE):
                    guard = o['guardrail']
                    expected = {Action.BLOCK_PRE_LEDGER: Step.BLOCK, Action.REQUIRE_HUMAN_CONFIRMATION: Step.REQUIRE_HUMAN,
                                Action.PROCEED_TO_DAML: Step.EXECUTE}[guard.action]
                    if step != expected:
                        raise ValidationError('Planner attempted to bypass guardrail')
                    state = {Step.BLOCK: State.BLOCKED, Step.REQUIRE_HUMAN: State.WAITING_FOR_HUMAN,
                             Step.EXECUTE: State.READY_FOR_EXECUTION}[step]
                    session.move(state, step, 'Guarded action selected; payment authority stays outside planner')
                    session.trace.append({'state': state.value, 'action': step.value, 'observation': guard.action.value,
                                          'public_reason': 'Assessment completed'})
                    return self._result(session), session
                else:
                    raise ValidationError('Unexpected planner action')
                session.trace.append({'state': session.machine.state.value, 'action': step.value,
                                      'observation': summary, 'public_reason': 'Resolve next required observation'})
            return self._fail(session, 'Maximum agent steps exceeded'), session
        except Exception:
            # Never expose arbitrary tool/model exception text (could contain credentials).
            return self._fail(session, 'Local agent failed safely; no execution permitted'), session

    def _blocked(self, session, error, reason):
        decision = AgentDecision(Action.BLOCK_PRE_LEDGER, '0', ('No execution permitted',))
        return Assessment(session.observed.get('intent'), session.observed.get('risk'), decision,
                          GuardrailResult(Action.BLOCK_PRE_LEDGER, Action.BLOCK_PRE_LEDGER, (reason,), ()),
                          tuple(session.invoked), (), error, state=session.machine.state,
                          transitions=tuple(session.machine.history), observations=tuple(session.trace), planner_action='BLOCK')

    def _fail(self, session, message):
        session.machine.transition(State.FAILED, 'BLOCK', message)
        return self._blocked(session, message, 'agent_failure')

    def _result(self, s):
        o = s.observed
        return Assessment(o['intent'], o['risk'], o['decision'], o['guardrail'], tuple(s.invoked), tuple(o['policy']),
                          features=o.get('features'), local_anomaly_score=o.get('anomaly_score'), state=s.machine.state,
                          transitions=tuple(s.machine.history), observations=tuple(s.trace), planner_action=s.selected)


def complete_assessment(assessment, controller, human_decision=None):
    """Application boundary: only ExecutionController can submit. No model/tool access."""
    from .ledger import ExecutionResult, MockPaymentExecutionAdapter
    if assessment.state not in (State.BLOCKED, State.FAILED, State.WAITING_FOR_HUMAN, State.READY_FOR_EXECUTION):
        raise ValidationError('Assessment is not eligible for outcome handling')
    machine = StateMachine(assessment.state, list(assessment.transitions))
    if assessment.action == Action.REQUIRE_HUMAN_CONFIRMATION and human_decision is True:
        machine.transition(State.READY_FOR_EXECUTION, 'HUMAN_APPROVED', 'Explicit approval of this assessment')
    if machine.state == State.READY_FOR_EXECUTION:
        machine.transition(State.EXECUTING, 'EXECUTE', 'Refresh deterministic preflight at execution boundary')
    try:
        result = controller.execute(assessment, human_decision)
    except Exception:
        machine.transition(State.FAILED, 'EXECUTION_FAILED', 'No automatic retry; outcome requires reconciliation')
        result = ExecutionResult('FAILED', 'Execution outcome uncertain; reconcile before retry',
                                 isinstance(controller.adapter, MockPaymentExecutionAdapter))
    if result.status == 'DECLINED':
        result = ExecutionResult('REJECTED_BY_HUMAN', 'Human rejected payment; no execution permitted', True)
    if result.status == 'AWAITING_HUMAN':
        if machine.state != State.WAITING_FOR_HUMAN:
            machine.transition(State.WAITING_FOR_HUMAN, 'REQUIRE_HUMAN', 'Fresh preflight requires explicit approval')
    else:
        if result.status == 'BLOCKED' and machine.state not in (State.BLOCKED, State.FAILED):
            machine.transition(State.BLOCKED, 'BLOCK', 'Execution preflight blocked')
        machine.transition(State.COMPLETED, 'COMPLETE', 'Outcome recorded: ' + result.status)
    return replace(assessment, state=machine.state, transitions=tuple(machine.history)), result


def run_events(agent, source, controller, *, review=None, memory=None, max_events=20):
    """Finite event loop; each feedback record is committed before next observation."""
    from .logging_utils import audit_record
    if type(max_events) is not int or not 1 <= max_events <= 1000:
        raise ValidationError('max_events must be between 1 and 1000')
    for event in islice(iter(source), max_events):
        assessment = agent.assess(event.request)
        human = review(assessment) if assessment.action == Action.REQUIRE_HUMAN_CONFIRMATION and review else None
        completed, result = complete_assessment(assessment, controller, human)
        record = audit_record(completed, result, human)
        record['event_id'] = event.event_id
        if memory is not None:
            memory.record_outcome(record, assessment.intent, result)
        yield record
