"""Read-only JSON snapshot repository; demo records are not ledger evidence."""
from typing import Protocol
from .config import HISTORY_PATH
from .models import Transaction, WalletContext, strict_json


class WalletContextProvider(Protocol):
    def snapshot(self) -> WalletContext: ...


def context_from_dict(data: dict) -> WalletContext:
    return WalletContext(data['balance'], data['daily_spend'],
                         tuple(Transaction(**t) for t in data.get('recent_transactions', [])))


class MockWalletContextProvider:
    def __init__(self, context: WalletContext | None = None):
        self.context = context or context_from_dict(strict_json(HISTORY_PATH.read_text()))

    def snapshot(self) -> WalletContext:
        return self.context


class LocalDemoMemory(MockWalletContextProvider):
    """Local JSON audit/outcome memory; mock reservations are NOT settled history.

    Optional file must have this schema. Existing fixture files are never accepted.
    No online learning from unverified submitted transactions.
    """
    def __init__(self, path=None, context=None):
        from pathlib import Path
        from decimal import Decimal
        from .models import ValidationError, decimal
        super().__init__(context)
        self.path = Path(path) if path is not None else None
        self.records = []
        self.reserved = Decimal('0')
        if self.path is not None and self.path.exists():
            data = strict_json(self.path.read_text())
            if set(data) != {'schema', 'reserved', 'records'} or data['schema'] != 'local-demo-v1' or not isinstance(data['records'], list):
                raise ValidationError('Not a local demo memory file')
            self.reserved = decimal(data['reserved'])
            if self.reserved < 0 or self.reserved > self.context.balance:
                raise ValidationError('Invalid mock reservation')
            self.records = data['records'][-1000:]

    def snapshot(self):
        from dataclasses import replace
        return replace(self.context, balance=self.context.balance - self.reserved,
                       daily_spend=self.context.daily_spend + self.reserved)

    def record_outcome(self, record, intent, result):
        import json
        import os
        import tempfile
        from .models import jsonable
        if result.status == 'WOULD_SUBMIT' and intent is not None:
            self.reserved += intent.amount
        self.records.append(record)
        self.records = self.records[-1000:]
        if self.path is not None:
            payload = json.dumps(jsonable({'schema': 'local-demo-v1', 'reserved': self.reserved, 'records': self.records}), indent=2)
            fd, name = tempfile.mkstemp(prefix='.agent-memory-', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    stream.write(payload)
                os.replace(name, self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
