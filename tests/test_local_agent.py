import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from ai_agent.agent_loop import LocalAgent, run_events, complete_assessment
from ai_agent.anomaly import default_model
from ai_agent.cli import main
from ai_agent.event_source import DemoEventSource, JsonlEventSource, StdinEventSource, PaymentEvent
from ai_agent.ledger import ExecutionController, MockPaymentExecutionAdapter
from ai_agent.memory import LocalDemoMemory, MockWalletContextProvider
from ai_agent.models import Action, ValidationError
from ai_agent.planner import AutonomousPlanner, Step
from ai_agent.state_machine import State, StateMachine


class StateTests(unittest.TestCase):
    def test_normal_sequence(self):
        machine = StateMachine()
        for state in (State.VALIDATING, State.GATHERING_CONTEXT, State.BUILDING_FEATURES,
                      State.ASSESSING_ANOMALY, State.ASSESSING_RISK, State.PLANNING,
                      State.WAITING_FOR_HUMAN, State.READY_FOR_EXECUTION, State.EXECUTING, State.COMPLETED):
            machine.transition(state, 'TEST', 'public reason')
        self.assertEqual(len(machine.history), 10)
        self.assertEqual(machine.history[0]['from'], 'RECEIVED')

    def test_illegal_transition(self):
        machine = StateMachine()
        with self.assertRaises(ValidationError): machine.transition(State.EXECUTING, 'EXECUTE', '')
        self.assertEqual(machine.state, State.RECEIVED)
        self.assertEqual(machine.history, [])

    def test_no_reopen_terminal(self):
        machine = StateMachine(State.COMPLETED)
        for state in State:
            with self.assertRaises(ValidationError): machine.transition(state, 'REOPEN', '')

    def test_fail_closed_sequence(self):
        machine = StateMachine()
        machine.transition(State.FAILED, 'FAIL', 'Budget exhausted')
        machine.transition(State.COMPLETED, 'COMPLETE', 'Recorded')
        self.assertEqual(machine.state, State.COMPLETED)

    def test_rejection_sequence(self):
        machine = StateMachine(State.WAITING_FOR_HUMAN)
        machine.transition(State.COMPLETED, 'REJECT', 'Human rejected')
        with self.assertRaises(ValidationError): machine.transition(State.EXECUTING, 'EXECUTE', '')


class PlannerTests(unittest.TestCase):
    def setUp(self): self.planner = AutonomousPlanner()

    def test_missing_intent_first(self):
        self.assertEqual(self.planner.next_step({}), Step.VALIDATE_INTENT)

    def test_invalid_intent_blocks_without_context(self):
        self.assertEqual(self.planner.next_step({'intent': None, 'invalid_intent': True}), Step.BLOCK)

    def test_skip_existing_balance(self):
        self.assertEqual(self.planner.next_step({'intent': object(), 'balance': {}}), Step.LOAD_POLICY)

    def test_history_before_features(self):
        o = {'intent': object(), 'balance': {}, 'policy': {}}
        self.assertEqual(self.planner.next_step(o), Step.FETCH_RECIPIENT_HISTORY)
        o['recipient_history'] = []
        self.assertEqual(self.planner.next_step(o), Step.FETCH_TRANSACTION_HISTORY)
        o['history'] = []
        self.assertEqual(self.planner.next_step(o), Step.BUILD_FEATURES)

    def test_early_block_skips_feature_and_ml(self):
        o = {'intent': object(), 'balance': {}, 'policy': {}, 'hard_block': True}
        self.assertEqual(self.planner.next_step(o), Step.ASSESS_RISK)
        o['risk'] = object()
        self.assertEqual(self.planner.next_step(o), Step.PLAN)
        o['guardrail'] = object()
        self.assertEqual(self.planner.next_step(o), Step.BLOCK)


class EventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.model = default_model()

    def setup_runner(self, memory=None, max_steps=20):
        memory = memory if memory is not None else LocalDemoMemory()
        agent = LocalAgent(context=memory, model=self.model, max_steps=max_steps)
        adapter = MockPaymentExecutionAdapter()
        controller = ExecutionController(adapter, memory, agent.policy)
        return agent, adapter, controller, memory

    def test_finite_demo_source(self): self.assertEqual(len(list(DemoEventSource())), 3)

    def test_multi_event_loop_with_feedback(self):
        agent, adapter, controller, memory = self.setup_runner()
        records = list(run_events(agent, DemoEventSource(), controller, memory=memory))
        self.assertEqual([r['execution_result']['status'] for r in records], ['WOULD_SUBMIT', 'AWAITING_HUMAN', 'BLOCKED'])
        self.assertEqual(len(adapter.records), 1)
        self.assertEqual(len(memory.records), 3)
        self.assertEqual(str(memory.reserved), '0.05')
        self.assertEqual(records[1]['agent_state'], 'WAITING_FOR_HUMAN')
        self.assertEqual(records[0]['agent_state'], 'COMPLETED')
        self.assertEqual(memory.snapshot().recent_transactions, MockWalletContextProvider().snapshot().recent_transactions)

    def test_human_approval(self):
        agent, adapter, controller, memory = self.setup_runner()
        review = Mock(return_value=True)
        records = list(run_events(agent, DemoEventSource(), controller, review=review, memory=memory))
        self.assertEqual(len(adapter.records), 2)
        review.assert_called_once()
        self.assertEqual(records[1]['execution_result']['status'], 'WOULD_SUBMIT')
        states = [t['to'] for t in records[1]['agent_state_transitions']]
        self.assertIn('WAITING_FOR_HUMAN', states)
        self.assertIn('EXECUTING', states)

    def test_human_rejection(self):
        agent, adapter, controller, memory = self.setup_runner()
        records = list(run_events(agent, DemoEventSource(), controller, review=lambda _: False, memory=memory))
        self.assertEqual(records[1]['execution_result']['status'], 'REJECTED_BY_HUMAN')
        self.assertEqual(len(adapter.records), 1)
        self.assertNotIn('EXECUTING', [t['to'] for t in records[1]['agent_state_transitions']])

    def test_hard_block_not_reviewed(self):
        agent, adapter, controller, memory = self.setup_runner()
        review = Mock(return_value=True)
        records = list(run_events(agent, [PaymentEvent('hard', 'Pay Alice 5 CC')], controller, review=review))
        review.assert_not_called()
        self.assertEqual(adapter.records, [])
        self.assertEqual(records[0]['execution_result']['status'], 'BLOCKED')

    def test_max_steps_prevents_submission(self):
        agent, adapter, controller, memory = self.setup_runner(max_steps=1)
        records = list(run_events(agent, DemoEventSource(), controller, review=lambda _: True))
        self.assertEqual(adapter.records, [])
        self.assertTrue(all(r['final_action'] == 'BLOCK_PRE_LEDGER' for r in records))

    def test_max_events_does_not_consume_extra(self):
        agent, adapter, controller, memory = self.setup_runner()
        consumed = []
        def source():
            for event in DemoEventSource():
                consumed.append(event)
                yield event
        self.assertEqual(len(list(run_events(agent, source(), controller, max_events=1))), 1)
        self.assertEqual(len(consumed), 1)

    def test_bounds_validation(self):
        for n in (0, -1, 101, True):
            with self.assertRaises(ValidationError): LocalAgent(max_steps=n)
        agent, _, controller, _ = self.setup_runner()
        for n in (0, 1001, True):
            with self.assertRaises(ValidationError): list(run_events(agent, [], controller, max_events=n))

    def test_jsonl_and_malformed_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.jsonl'
            path.write_text('{"request":"Pay Alice 0.05 CC"}\n{bad\n{"request":"Pay Alice 5 CC","extra":1}\n')
            agent, adapter, controller, memory = self.setup_runner()
            records = list(run_events(agent, JsonlEventSource(path), controller))
            self.assertEqual([r['final_action'] for r in records], ['PROCEED_TO_DAML', 'BLOCK_PRE_LEDGER', 'BLOCK_PRE_LEDGER'])
            self.assertEqual(len(adapter.records), 1)

    def test_stdin_finite(self):
        with patch('builtins.input', side_effect=['Pay Alice 0.05 CC', '']):
            self.assertEqual(len(list(StdinEventSource())), 1)
        with patch('builtins.input', side_effect=EOFError):
            self.assertEqual(list(StdinEventSource()), [])

    def test_local_memory_roundtrip_and_fixture_isolation(self):
        fixture = Path('data/demo_history.json')
        before = fixture.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'memory.json'
            agent, _, controller, memory = self.setup_runner(LocalDemoMemory(path))
            list(run_events(agent, DemoEventSource(), controller, memory=memory))
            loaded = LocalDemoMemory(path)
            self.assertEqual(len(loaded.records), 3)
            self.assertEqual(loaded.snapshot(), memory.snapshot())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(LocalDemoMemory().records), 0)
        self.assertEqual(fixture.read_bytes(), before)
        with self.assertRaises(ValidationError): LocalDemoMemory(fixture)
        self.assertEqual(fixture.read_bytes(), before)

    def test_reservations_affect_next_event(self):
        agent, adapter, controller, memory = self.setup_runner()
        events = [PaymentEvent(str(i), 'Pay Alice 0.19 CC') for i in range(10)]
        records = list(run_events(agent, events, controller, memory=memory, review=lambda _: True))
        self.assertLess(len(adapter.records), 10)
        self.assertGreaterEqual(memory.snapshot().balance, 0)
        self.assertEqual(records[-1]['final_action'], 'BLOCK_PRE_LEDGER')

    def test_jsonl_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'queue.jsonl'
            path.write_text('{"request":"Pay Alice 0.05 CC"}\n')
            with patch('sys.stdout', new_callable=io.StringIO) as out:
                self.assertEqual(main(['run-agent', '--source', 'jsonl', '--file', str(path)]), 0)
            self.assertIn('WOULD_SUBMIT', out.getvalue())

    def test_model_info_cli(self):
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(main(['model-info']), 0)
        self.assertEqual(json.loads(out.getvalue())['model_type'], 'LocalKNNAnomalyModel')

    def test_completed_outcome_cannot_be_reexecuted(self):
        agent, adapter, controller, _ = self.setup_runner()
        completed, result = complete_assessment(agent.assess('Pay Alice 0.05 CC'), controller)
        with self.assertRaises(ValidationError): complete_assessment(completed, controller)
        self.assertEqual(len(adapter.records), 1)

    def test_execution_exception_is_sanitized_and_consumed(self):
        agent, adapter, controller, _ = self.setup_runner()
        assessment = agent.assess('Pay Alice 0.05 CC')
        with patch.object(adapter, 'submit', side_effect=RuntimeError('secret-token')) as submit:
            completed, result = complete_assessment(assessment, controller)
            self.assertEqual(result.status, 'FAILED')
            self.assertNotIn('secret-token', result.detail)
            self.assertEqual(controller.execute(assessment).status, 'ALREADY_HANDLED')
            submit.assert_called_once()
        self.assertEqual(completed.state, State.COMPLETED)
        self.assertIn('FAILED', [row['to'] for row in completed.transitions])

    def test_audit_contains_state_features_and_no_raw_history(self):
        from ai_agent.logging_utils import audit_record
        agent, _, _, _ = self.setup_runner()
        record = audit_record(agent.assess('Pay Alice 0.05 CC'))
        for key in ('agent_state_transitions', 'agent_observations', 'features', 'anomaly_score',
                    'planner_action', 'guardrail_action', 'human_decision', 'execution_result'):
            self.assertIn(key, record)
        self.assertNotIn('recent_transactions', json.dumps(record))
        self.assertTrue(record['agent_state_transitions'])
