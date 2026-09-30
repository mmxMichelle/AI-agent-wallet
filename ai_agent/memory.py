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
