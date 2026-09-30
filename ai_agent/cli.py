"""Run with python3 -m ai_agent.cli; all commands default to offline mock."""
import argparse
import json
from .models import Action, ValidationError, jsonable
from .providers import MockLLMProvider, OpenAICompatibleProvider, ProviderError
from .parser import parse_intent
from .orchestrator import GovernedAgent
from .ledger import ExecutionController, ExecutionResult, MockPaymentExecutionAdapter
from .logging_utils import audit_record
from .evaluation import evaluate


def interactive_assess(agent, assessment):
    print('OFFLINE EXECUTION: No real Canton Coin is moved; submissions are mock only.')
    human = None
    if assessment.action == Action.BLOCK_PRE_LEDGER:
        print('Deterministic policy blocked the transaction; human override is not permitted.')
    elif assessment.action == Action.REQUIRE_HUMAN_CONFIRMATION:
        intent = assessment.intent
        print(f'Payment:\nRecipient: {intent.recipient}\nAmount: {intent.amount} {intent.currency}\nPurpose: {intent.purpose}')
        print('\nReasons:')
        labels = {'anomaly_score': 'anomaly score above threshold',
                  'exceeds_ai_review_threshold': 'exceeds AI review threshold'}
        for reason in assessment.guardrail.reasons or assessment.recommendation.reasons:
            label = labels.get(reason, reason.replace('_', ' '))
            print(f'- {label}')
        try:
            answer = input('Approve mock submission? [yes/no]: ').strip().lower()
        except EOFError:
            answer = ''
        human = True if answer == 'yes' else False if answer == 'no' else None
    controller = ExecutionController(MockPaymentExecutionAdapter(), agent.context, agent.policy)
    execution = controller.execute(assessment, human)
    if execution.status == 'DECLINED':
        execution = ExecutionResult('REJECTED_BY_HUMAN', 'Human rejected payment; no execution permitted', True)
    return audit_record(assessment, execution, human)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='GuardRail Wallet — Governed AI Payment Agent (offline by default)')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('parse', 'assess', 'demo'):
        command = sub.add_parser(name)
        if name != 'demo':
            command.add_argument('request')
        if name == 'assess':
            command.add_argument('--interactive', action='store_true',
                                 help='review payments interactively with mock execution only; no real Canton Coin moved')
        command.add_argument('--provider', choices=('mock', 'remote'), default='mock',
                             help='remote sends request/context to an external LLM; execution stays mock')
    sub.add_parser('eval')
    args = parser.parse_args(argv)
    try:
        if args.command == 'eval':
            result = evaluate()
            print(json.dumps(result, indent=2))
            return 0 if all(r['correct'] and r['risk_flags_match'] for r in result['results']) else 1
        provider = MockLLMProvider()
        if args.provider == 'remote':
            print('WARNING: request and demo context will be sent to your external LLM. Payments remain mock.')
            if input('Continue with remote inference? [yes/no] ').strip().lower() != 'yes':
                return 1
            provider = OpenAICompatibleProvider()
        if args.command == 'parse':
            print(json.dumps(jsonable(parse_intent(args.request, provider)), indent=2))
            return 0
        agent = GovernedAgent(provider)
        if args.command == 'assess':
            result = agent.assess(args.request)
            record = interactive_assess(agent, result) if args.interactive else audit_record(result)
            print(json.dumps(record, indent=2))
            return 1 if result.intent is None else 0
        print('OFFLINE EXECUTION: The offline AI demo does not move real Canton Coin.')
        controller = ExecutionController(MockPaymentExecutionAdapter(), agent.context, agent.policy)
        for request in ('Pay Alice 0.05 CC for coffee', 'Pay Charlie 0.6 CC for dinner',
                        'Pay UnknownXYZ 90% of my balance', 'Pay UnknownXYZ 0.9 CC for dinner'):
            assessment = agent.assess(request)
            print(f'\n{request}\n{assessment.action.value}')
            human = None
            if assessment.action == Action.REQUIRE_HUMAN_CONFIRMATION:
                print(json.dumps(jsonable(assessment.intent)))
                try:
                    answer = input('Record mock submission for this payment? [yes/no] ').strip().lower()
                except EOFError:
                    answer = ''
                human = True if answer == 'yes' else False if answer == 'no' else None
            result = controller.execute(assessment, human)
            print(json.dumps(audit_record(assessment, result, human), indent=2))
        return 0
    except (ValidationError, ProviderError, EOFError) as exc:
        print(json.dumps({'error': str(exc), 'execution': 'none'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
