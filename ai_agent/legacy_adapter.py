"""Optional explicit integration. No legacy imports until a live method is called."""
from decimal import Decimal
from .models import PaymentIntent, WalletContext, ValidationError, decimal
from .ledger import ExecutionResult


class LegacyWalletContextProvider:
    def __init__(self, party: str, history: WalletContext, *, enabled: bool = False):
        self.party, self.history, self.enabled = party, history, enabled

    def snapshot(self) -> WalletContext:
        if not self.enabled or not self.party:
            raise ValidationError('Live context disabled; use MockWalletContextProvider')
        import c8lab
        balance = sum((decimal(h['amount']) for h in c8lab.holdings(self.party)
                       if h.get('instrument') == 'Amulet' and not h.get('locked')), Decimal('0'))
        return WalletContext(balance, self.history.daily_spend, self.history.recent_transactions)


class LegacyDamlPaymentExecutionAdapter:
    """One-shot Mandate submission wrapper; never settles or approves.

    Mandate IDs/threshold/party mapping come from trusted application setup.
    Daml independently enforces them. Owner approval and settlement continue
    through existing tooling. This adapter has not been live-verified.
    """
    def __init__(self, mandate_cid: str, spender_party: str, approval_threshold: str,
                 recipients: dict[str, str], *, enabled: bool = False):
        self.mandate_cid, self.spender_party = mandate_cid, spender_party
        self.threshold = decimal(approval_threshold)
        self.recipients, self.enabled = dict(recipients), enabled
        self.used = False

    def submit(self, intent: PaymentIntent) -> ExecutionResult:
        if not self.enabled or not self.mandate_cid or not self.spender_party or self.threshold <= 0:
            raise ValidationError('Live Mandate configuration missing or disabled; use mock mode')
        if self.used or intent.recipient not in self.recipients:
            raise ValidationError('Adapter already used or recipient lacks an explicit party mapping')
        from python import mandate_client as mc
        builder = mc.charge_command if intent.amount < self.threshold else mc.request_high_value_command
        command = builder(self.mandate_cid, str(intent.amount), self.recipients[intent.recipient], intent.purpose)
        self.used = True
        mc.submit_command([command], act_as=[self.spender_party])
        return ExecutionResult('SUBMITTED_TO_DAML',
                               'Mandate command submitted; continue existing owner approval/settlement workflow', False)
