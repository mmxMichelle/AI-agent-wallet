"""Local autonomous agent CLI. No network inference or credential configuration."""
import argparse
import json
from .models import Action, ValidationError, jsonable
from .parser import parse_intent
from .orchestrator import GovernedAgent
from .agent_loop import complete_assessment, run_events
from .ledger import ExecutionController, MockPaymentExecutionAdapter
from .logging_utils import audit_record
from .evaluation import evaluate
from .event_source import DemoEventSource, JsonlEventSource, StdinEventSource
from .memory import LocalDemoMemory
from .anomaly import default_model, model_info


def ask_human(assessment):
    intent = assessment.intent
    print(f'Payment:\nRecipient: {intent.recipient}\nAmount: {intent.amount} {intent.currency}\nPurpose: {intent.purpose}')
    print('WAITING_FOR_HUMAN\nReasons:')
    labels = {'anomaly_score': 'anomaly score above threshold',
              'exceeds_ai_review_threshold': 'exceeds AI review threshold'}
    for reason in assessment.guardrail.reasons or assessment.recommendation.reasons:
        print('- ' + labels.get(reason, reason.replace('_', ' ')))
    try:
        answer = input('Approve mock submission? [yes/no]: ').strip().lower()
    except EOFError:
        answer = ''
    return True if answer == 'yes' else False if answer == 'no' else None


def interactive_assess(agent, assessment):
    print('OFFLINE EXECUTION: No real Canton Coin is moved; submissions are mock only.')
    human = None
    if assessment.action == Action.BLOCK_PRE_LEDGER:
        print('Deterministic policy blocked the transaction; human override is not permitted.')
    elif assessment.action == Action.REQUIRE_HUMAN_CONFIRMATION:
        human = ask_human(assessment)
    controller = ExecutionController(MockPaymentExecutionAdapter(), agent.context, agent.policy)
    completed, execution = complete_assessment(assessment, controller, human)
    return audit_record(completed, execution, human)


def main(argv=None):
    parser = argparse.ArgumentParser(description='GuardRail Wallet — Privacy-Preserving Autonomous AI Payment Agent')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('parse', 'assess'):
        command = sub.add_parser(name)
        command.add_argument('request')
        if name == 'assess':
            command.add_argument('--interactive', action='store_true')
            command.add_argument('--max-steps', type=int, default=20)
    for name in ('demo', 'run-agent'):
        command = sub.add_parser(name)
        command.add_argument('--source', choices=('demo', 'stdin', 'jsonl'), default='demo')
        command.add_argument('--file', help='local JSONL file containing {"request": "..."} lines')
        command.add_argument('--memory', help='optional local demo JSON memory; contains sensitive local audit data')
        command.add_argument('--max-events', type=int, default=20)
        command.add_argument('--max-steps', type=int, default=20)
        command.add_argument('--non-interactive', action='store_true', help='leave reviews waiting without prompting')
    sub.add_parser('eval')
    sub.add_parser('model-info')
    args = parser.parse_args(argv)
    try:
        if args.command == 'eval':
            report = evaluate()
            print(json.dumps(report, indent=2))
            return 0 if all(r['correct'] and r['risk_flags_match'] for r in report['results']) else 1
        if args.command == 'model-info':
            print(json.dumps(model_info(default_model()), indent=2))
            return 0
        if args.command == 'parse':
            print(json.dumps(jsonable(parse_intent(args.request)), indent=2))
            return 0
        if args.command == 'assess':
            agent = GovernedAgent(max_steps=args.max_steps)
            assessment = agent.assess(args.request)
            print(json.dumps(interactive_assess(agent, assessment) if args.interactive else audit_record(assessment), indent=2))
            return 1 if assessment.error else 0
        if args.source == 'jsonl' and not args.file:
            raise ValidationError('--file is required for JSONL source')
        source = {'demo': DemoEventSource, 'stdin': StdinEventSource}.get(args.source)
        source = source() if source else JsonlEventSource(args.file)
        memory = LocalDemoMemory(args.memory)
        agent = GovernedAgent(context=memory, max_steps=args.max_steps)
        controller = ExecutionController(MockPaymentExecutionAdapter(), memory, agent.policy)
        print('OFFLINE EXECUTION: No real Canton Coin is moved; submissions are mock only.')
        for record in run_events(agent, source, controller, review=None if args.non_interactive else ask_human,
                                 memory=memory, max_events=args.max_events):
            print(json.dumps(record, indent=2))
        return 0
    except (ValidationError, OSError):
        print(json.dumps({'error': 'Invalid local input/configuration or unavailable local file; no further execution', 'execution': 'none'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
