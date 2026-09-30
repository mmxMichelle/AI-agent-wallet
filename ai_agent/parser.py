"""Deliberately limited financial grammar: ambiguity is never guessed."""
import re
from .models import PaymentIntent, ValidationError


class ClarificationRequired(ValidationError):
    pass


# ASCII amounts only. Recipient identifiers are explicit names, not descriptions.
_NAME = r"[A-Za-z][A-Za-z0-9_'\-]*(?: [A-Za-z][A-Za-z0-9_'\-]*)*?"
_AMOUNT = r'[+-]?[0-9]+(?:\.[0-9]+)?'
_PATTERNS = (
    rf'(?:Pay|Send) (?P<recipient>{_NAME}) (?P<amount>{_AMOUNT}) (?P<currency>[A-Za-z]+)(?: for (?P<purpose>.+))?',
    rf'(?:Send|Transfer) (?P<amount>{_AMOUNT}) (?P<currency>[A-Za-z]+) to (?P<recipient>{_NAME})(?: for (?P<purpose>.+))?',
)
_AMBIGUOUS = {'whoever', 'someone', 'somebody', 'yesterday', 'normally', 'around', 'roughly', 'approximately', 'or', 'and'}


def parse_intent(request: str) -> PaymentIntent:
    if isinstance(request, str) and 0 < len(request) <= 4000:
        for pattern in _PATTERNS:
            match = re.fullmatch(pattern, request.strip(), re.I)
            if match:
                data = match.groupdict()
                if not set(data['recipient'].lower().split()) & _AMBIGUOUS:
                    try:
                        return PaymentIntent(data['recipient'], data['amount'], data['currency'].upper(), data['purpose'] or '')
                    except ValidationError:
                        break
    raise ClarificationRequired('CLARIFICATION_REQUIRED: specify one recipient, an exact positive amount, and CC currency')
