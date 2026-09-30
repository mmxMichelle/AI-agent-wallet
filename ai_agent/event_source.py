"""Finite local input sources. No queue service or ledger connection."""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Iterator
from .models import strict_json, ValidationError


@dataclass(frozen=True)
class PaymentEvent:
    event_id: str
    request: str


class PaymentEventSource(Protocol):
    def __iter__(self) -> Iterator[PaymentEvent]: ...


class DemoEventSource:
    def __iter__(self):
        for number, request in enumerate(('Pay Alice 0.05 CC for coffee', 'Pay Charlie 0.6 CC for dinner',
                                          'Pay UnknownXYZ 0.9 CC for dinner'), 1):
            yield PaymentEvent('demo-' + str(number), request)


class JsonlEventSource:
    def __init__(self, path):
        self.path = Path(path)

    def __iter__(self):
        with self.path.open() as stream:
            for number in range(1, 1001):
                line = stream.readline(8193)
                if not line:
                    break
                try:
                    if len(line) > 8192:
                        raise ValidationError('Oversized local event')
                    data = strict_json(line)
                    if set(data) != {'request'} or not isinstance(data['request'], str):
                        raise ValidationError('Invalid event schema')
                    request = data['request']
                except ValidationError:
                    request = ''  # Every malformed event receives a blocked audit record.
                yield PaymentEvent('jsonl-' + str(number), request)
                if len(line) > 8192:
                    break


class StdinEventSource:
    def __iter__(self):
        for number in range(1, 1001):
            try:
                request = input('Payment request (blank to stop): ')
            except EOFError:
                break
            if not request.strip():
                break
            yield PaymentEvent('stdin-' + str(number), request)
