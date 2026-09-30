#!/usr/bin/env python3
"""One-page GuardRail Wallet demo UI."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import pathlib
import sys
import threading
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import c8lab  # noqa: E402
import mandate_client as mc  # noqa: E402


DEFAULT_SPENDER = "guardrail-agent::12204e94c0e449c0efcd270dd1e68259c36471cebef132e5c7dfc2750fe8c9eed77f"
DEFAULT_RECIPIENT = "guardrail-vendor::12204e94c0e449c0efcd270dd1e68259c36471cebef132e5c7dfc2750fe8c9eed77f"
DEFAULT_THRESHOLD = Decimal("0.20")
DEFAULT_CAP = Decimal("2.00")
DEFAULT_SMALL_PAYMENT = Decimal("0.10")
DEFAULT_LARGE_PAYMENT = Decimal("0.50")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def tomorrow_iso() -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_decimal(value: str, field_name: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc


def format_cc(value: Decimal | str | float | int | None) -> str:
    if value is None:
        return "—"
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    return f"{dec.quantize(Decimal('0.01'))}"


def policy_decision(amount: Decimal, threshold: Decimal) -> str:
    return "AUTO APPROVED" if amount < threshold else "HUMAN APPROVAL REQUIRED"


def sum_holdings(holdings: list[dict[str, Any]]) -> Decimal:
    total = Decimal("0")
    for h in holdings:
        if h.get("instrument") == "Amulet":
            total += Decimal(str(h.get("amount", "0")))
    return total


def extract_created(response: dict[str, Any], suffix: str) -> str | None:
    for event in mc.extract_created_events(response):
        if event["templateId"].endswith(suffix):
            return event["contractId"] or None
    return None


class DemoState:
    def __init__(self, offline_demo: bool = False) -> None:
        self.lock = threading.RLock()
        self.offline_demo = offline_demo
        self.owner_party = os.environ.get("GUARDRAIL_OWNER_PARTY", "guardrail-owner::demo")
        self.spender_party = DEFAULT_SPENDER
        self.recipient_party = DEFAULT_RECIPIENT
        self.preapproval_provider = os.environ.get("GUARDRAIL_PREAPPROVAL_PROVIDER", "app_user")
        self.approval_threshold = DEFAULT_THRESHOLD
        self.spending_cap = DEFAULT_CAP
        self.payment_amount = DEFAULT_SMALL_PAYMENT
        self.payment_recipient = self.recipient_party
        self.payment_purpose = "GuardRail demo payment"
        self.expires_at = tomorrow_iso()
        self.package_ref = mc.DEFAULT_PACKAGE_REF
        self.mandate_proposal_cid = ""
        self.mandate_cid = ""
        self.pending_payment_cid = ""
        self.transaction_record_cid = ""
        self.transfer_kind = ""
        self.instruction_cid = ""
        self.policy_state = "READY"
        self.settlement_state = "WAITING"
        self.environment_state = self._environment_state()
        self.balance_state = "Not refreshed yet"
        self.agent_balance: Decimal | None = None
        self.vendor_balance: Decimal | None = None
        self.audit: list[dict[str, str]] = [
            {
                "time": now_iso().replace("T", " ").replace("Z", "")[:8],
                "label": "UI ready",
                "detail": "Open the demo and press Create Demo Mandate",
            }
        ]
        self.last_error = ""

    def _environment_state(self) -> str:
        if self.offline_demo:
            return "DEMO RECORDING MODE"
        if os.environ.get("C8_BASE") and os.environ.get("C8_IDP") and os.environ.get("C8_CLIENT_SECRET"):
            return "DEVNET READY"
        return "DEMO MODE"

    def append_audit(self, label: str, detail: str) -> None:
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        self.audit.append({"time": stamp, "label": label, "detail": detail})
        self.audit = self.audit[-30:]

    def to_dict(self) -> dict[str, Any]:
        with self.lock:
            return {
                "owner_party": self.owner_party,
                "spender_party": self.spender_party,
                "recipient_party": self.recipient_party,
                "preapproval_provider": self.preapproval_provider,
                "approval_threshold": format_cc(self.approval_threshold),
                "spending_cap": format_cc(self.spending_cap),
                "payment_amount": format_cc(self.payment_amount),
                "payment_recipient": self.payment_recipient,
                "payment_purpose": self.payment_purpose,
                "expires_at": self.expires_at,
                "mandate_proposal_cid": self.mandate_proposal_cid,
                "mandate_cid": self.mandate_cid,
                "pending_payment_cid": self.pending_payment_cid,
                "transaction_record_cid": self.transaction_record_cid,
                "transfer_kind": self.transfer_kind,
                "instruction_cid": self.instruction_cid,
                "policy_state": self.policy_state,
                "settlement_state": self.settlement_state,
                "environment_state": self.environment_state,
                "balance_state": self.balance_state,
                "agent_balance": format_cc(self.agent_balance),
                "vendor_balance": format_cc(self.vendor_balance),
                "audit": list(self.audit),
                "last_error": self.last_error,
            }

    def set_error(self, message: str) -> dict[str, Any]:
        self.last_error = message
        self.append_audit("ERROR", message)
        return {"ok": False, "error": message, "state": self.to_dict()}

    def refresh_balances(self) -> dict[str, Any]:
        try:
            if self.offline_demo:
                self.balance_state = "Balances refreshed"
                self.last_error = ""
                self.append_audit(
                    "Balances refreshed",
                    f"agent {format_cc(self.agent_balance)} CC, vendor {format_cc(self.vendor_balance)} CC",
                )
                return {"ok": True, "message": "Balances refreshed", "state": self.to_dict()}
            agent_holdings = c8lab.holdings(self.spender_party)
            vendor_holdings = c8lab.holdings(self.recipient_party)
            self.agent_balance = sum_holdings(agent_holdings)
            self.vendor_balance = sum_holdings(vendor_holdings)
            self.balance_state = "Balances refreshed"
            self.last_error = ""
            self.append_audit("Balances refreshed", f"agent {format_cc(self.agent_balance)} CC, vendor {format_cc(self.vendor_balance)} CC")
            return {"ok": True, "message": "Balances refreshed", "state": self.to_dict()}
        except Exception as exc:  # pragma: no cover - network dependent
            return self.set_error(str(exc))

    def configure_demo(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.owner_party = payload.get("owner_party", self.owner_party).strip()
            self.spender_party = payload.get("spender_party", self.spender_party).strip() or DEFAULT_SPENDER
            self.recipient_party = payload.get("recipient_party", self.recipient_party).strip() or DEFAULT_RECIPIENT
            self.preapproval_provider = payload.get("preapproval_provider", self.preapproval_provider).strip()
            self.approval_threshold = parse_decimal(payload.get("approval_threshold", str(self.approval_threshold)), "Approval Threshold")
            self.spending_cap = parse_decimal(payload.get("spending_cap", str(self.spending_cap)), "Spending Cap")
            self.payment_amount = parse_decimal(payload.get("payment_amount", str(self.payment_amount)), "Payment Amount")
            self.payment_recipient = payload.get("payment_recipient", self.recipient_party).strip() or self.recipient_party
            self.payment_purpose = payload.get("payment_purpose", self.payment_purpose).strip() or self.payment_purpose
            self.expires_at = payload.get("expires_at", self.expires_at).strip() or tomorrow_iso()
            self.policy_state = "CONFIGURED"
            self.append_audit("Demo configured", f"threshold {format_cc(self.approval_threshold)} CC, cap {format_cc(self.spending_cap)} CC")
            return {"ok": True, "message": "Demo configuration updated", "state": self.to_dict()}

    def create_demo_mandate(self) -> dict[str, Any]:
        with self.lock:
            if not self.owner_party:
                return self.set_error("Owner party is required to create the demo mandate.")
            try:
                if self.offline_demo:
                    self.mandate_proposal_cid = "proposal-demo-001"
                    self.mandate_cid = "mandate-demo-001"
                    self.pending_payment_cid = ""
                    self.transaction_record_cid = ""
                    self.transfer_kind = ""
                    self.instruction_cid = ""
                    self.policy_state = "MANDATE READY"
                    self.settlement_state = "WAITING"
                    self.last_error = ""
                    self.append_audit(
                        "Mandate ready",
                        f"threshold {format_cc(self.approval_threshold)} CC, cap {format_cc(self.spending_cap)} CC",
                    )
                    return {
                        "ok": True,
                        "message": "Demo mandate created",
                        "state": self.to_dict(),
                        "proposal": {"offline": True},
                        "mandate": {"offline": True},
                    }
                proposal = mc.submit_command(
                    [mc.create_proposal_command(
                        self.owner_party,
                        self.spender_party,
                        self.recipient_party,
                        self.spending_cap,
                        self.approval_threshold,
                        self.expires_at,
                        package_ref=self.package_ref,
                    )],
                    act_as=[self.owner_party],
                )
                proposal_cid = extract_created(proposal, ":Mandate:MandateProposal")
                if proposal_cid:
                    self.mandate_proposal_cid = proposal_cid
                mandate = mc.submit_command(
                    [mc.accept_proposal_command(self.mandate_proposal_cid, package_ref=self.package_ref)],
                    act_as=[self.spender_party],
                )
                mandate_cid = extract_created(mandate, ":Mandate:Mandate")
                if mandate_cid:
                    self.mandate_cid = mandate_cid
                self.pending_payment_cid = ""
                self.transaction_record_cid = ""
                self.transfer_kind = ""
                self.instruction_cid = ""
                self.policy_state = "MANDATE READY"
                self.settlement_state = "WAITING"
                self.last_error = ""
                self.append_audit("Mandate ready", f"threshold {format_cc(self.approval_threshold)} CC, cap {format_cc(self.spending_cap)} CC")
                return {"ok": True, "message": "Demo mandate created", "state": self.to_dict(), "proposal": proposal, "mandate": mandate}
            except Exception as exc:
                return self.set_error(str(exc))

    def enable_preapproval(self) -> dict[str, Any]:
        with self.lock:
            try:
                if self.offline_demo:
                    self.policy_state = "PREAPPROVAL REQUESTED"
                    self.append_audit("Preapproval requested", f"receiver {self.recipient_party}")
                    return {
                        "ok": True,
                        "message": "Transfer preapproval proposal created",
                        "state": self.to_dict(),
                        "result": {"offline": True},
                    }
                provider = self.preapproval_provider.strip() or None
                result = c8lab.create_preapproval_proposal(self.recipient_party, provider)
                self.policy_state = "PREAPPROVAL REQUESTED"
                self.append_audit("Preapproval requested", f"receiver {self.recipient_party}")
                return {"ok": True, "message": "Transfer preapproval proposal created", "state": self.to_dict(), "result": result}
            except Exception as exc:
                return self.set_error(str(exc))

    def _settle(self, amount: Decimal) -> dict[str, Any]:
        if self.offline_demo:
            if self.transfer_kind == "direct":
                self.agent_balance = (self.agent_balance or Decimal("0")) - amount
                self.vendor_balance = (self.vendor_balance or Decimal("0")) + amount
                self.settlement_state = "DIRECT"
                self.append_audit("Canton settlement", "DIRECT")
                self.append_audit("Payment completed", f"{format_cc(amount)} CC")
                return {"transferKind": "direct", "instructionCid": "", "result": {"offline": True}}
            self.settlement_state = "RECEIVER ACCEPTANCE REQUIRED"
            self.append_audit("Canton settlement", "RECEIVER ACCEPTANCE REQUIRED")
            return {"transferKind": "offer", "instructionCid": "instruction-demo-001", "result": {"offline": True}}
        result = mc.settle_payment(self.spender_party, self.payment_recipient, amount)
        self.transfer_kind = str(result.get("transferKind", ""))
        self.instruction_cid = str(result.get("instructionCid", ""))
        if self.transfer_kind == "direct":
            self.settlement_state = "DIRECT"
            self.append_audit("Canton settlement", "DIRECT")
            self.append_audit("Payment completed", f"{format_cc(amount)} CC")
        elif self.transfer_kind == "offer":
            self.settlement_state = "RECEIVER ACCEPTANCE REQUIRED"
            self.append_audit("Canton settlement", "RECEIVER ACCEPTANCE REQUIRED")
        else:
            self.settlement_state = self.transfer_kind or "UNKNOWN"
            self.append_audit("Canton settlement", self.settlement_state)
        return result

    def request_payment(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if not self.mandate_cid:
                return self.set_error("Create a demo mandate first.")
            try:
                amount = parse_decimal(payload.get("amount", str(self.payment_amount)), "Amount")
            except ValueError as exc:
                return self.set_error(str(exc))
            recipient = payload.get("recipient", self.payment_recipient).strip() or self.recipient_party
            purpose = payload.get("purpose", self.payment_purpose).strip() or self.payment_purpose
            self.payment_amount = amount
            self.payment_recipient = recipient
            self.payment_purpose = purpose
            self.last_error = ""
            self.append_audit("Payment requested", f"{format_cc(amount)} CC")
            try:
                if amount < self.approval_threshold:
                    self.policy_state = "AUTO APPROVED"
                    self.append_audit("Policy check", "AUTO APPROVED")
                    if self.offline_demo:
                        self.transfer_kind = "direct"
                        self.instruction_cid = ""
                        self.transaction_record_cid = "transaction-demo-001"
                        self.agent_balance = (self.agent_balance or Decimal("0")) - amount
                        self.vendor_balance = (self.vendor_balance or Decimal("0")) + amount
                        self.settlement_state = "DIRECT"
                        self.append_audit("Canton settlement", "DIRECT")
                        self.append_audit("Payment completed", f"{format_cc(amount)} CC")
                        self.refresh_balances()
                        return {
                            "ok": True,
                            "message": "Payment auto-approved and settled",
                            "state": self.to_dict(),
                            "response": {"offline": True},
                        }
                    response = mc.submit_command(
                        [mc.charge_command(self.mandate_cid, amount, recipient, purpose, package_ref=self.package_ref)],
                        act_as=[self.spender_party],
                    )
                    self.mandate_cid = extract_created(response, ":Mandate:Mandate") or self.mandate_cid
                    self.transaction_record_cid = extract_created(response, ":Mandate:TransactionRecord") or self.transaction_record_cid
                    self._settle(amount)
                    self.refresh_balances()
                    return {"ok": True, "message": "Payment auto-approved and settled", "state": self.to_dict(), "response": response}
                self.policy_state = "HUMAN APPROVAL REQUIRED"
                self.append_audit("Policy check", "HUMAN APPROVAL REQUIRED")
                if self.offline_demo:
                    self.pending_payment_cid = "pending-demo-001"
                    self.transfer_kind = ""
                    self.instruction_cid = ""
                    self.append_audit("Payment paused", "Waiting for owner approval")
                    return {
                        "ok": True,
                        "message": "Payment paused for human approval",
                        "state": self.to_dict(),
                        "response": {"offline": True},
                    }
                response = mc.submit_command(
                    [mc.request_high_value_command(self.mandate_cid, amount, recipient, purpose, package_ref=self.package_ref)],
                    act_as=[self.spender_party],
                )
                self.pending_payment_cid = extract_created(response, ":Mandate:PendingPayment") or self.pending_payment_cid
                self.append_audit("Payment paused", "Waiting for owner approval")
                return {"ok": True, "message": "Payment paused for human approval", "state": self.to_dict(), "response": response}
            except Exception as exc:
                return self.set_error(str(exc))

    def approve_payment(self) -> dict[str, Any]:
        with self.lock:
            if not self.pending_payment_cid:
                return self.set_error("No pending payment to approve.")
            try:
                self.append_audit("Owner action", "Approve")
                if self.offline_demo:
                    self.transaction_record_cid = "transaction-demo-002"
                    self.policy_state = "OWNER APPROVED"
                    self.append_audit("Policy decision", "OWNER APPROVED")
                    self.transfer_kind = "direct"
                    self.instruction_cid = ""
                    self.agent_balance = (self.agent_balance or Decimal("0")) - self.payment_amount
                    self.vendor_balance = (self.vendor_balance or Decimal("0")) + self.payment_amount
                    self.settlement_state = "DIRECT"
                    self.append_audit("Canton settlement", "DIRECT")
                    self.append_audit("Payment completed", f"{format_cc(self.payment_amount)} CC")
                    self.pending_payment_cid = ""
                    self.refresh_balances()
                    return {
                        "ok": True,
                        "message": "Pending payment approved and settled",
                        "state": self.to_dict(),
                        "response": {"offline": True},
                    }
                response = mc.submit_command(
                    [mc.approve_command(self.pending_payment_cid, package_ref=self.package_ref)],
                    act_as=[self.owner_party],
                )
                self.mandate_cid = extract_created(response, ":Mandate:Mandate") or self.mandate_cid
                self.transaction_record_cid = extract_created(response, ":Mandate:TransactionRecord") or self.transaction_record_cid
                self.policy_state = "OWNER APPROVED"
                self.append_audit("Policy decision", "OWNER APPROVED")
                self._settle(self.payment_amount)
                self.pending_payment_cid = ""
                self.refresh_balances()
                return {"ok": True, "message": "Pending payment approved and settled", "state": self.to_dict(), "response": response}
            except Exception as exc:
                return self.set_error(str(exc))

    def reject_payment(self) -> dict[str, Any]:
        with self.lock:
            if not self.pending_payment_cid:
                return self.set_error("No pending payment to reject.")
            try:
                self.append_audit("Owner action", "Reject")
                if self.offline_demo:
                    self.transaction_record_cid = "transaction-demo-003"
                    self.policy_state = "REJECTED BY POLICY"
                    self.settlement_state = "NOT SETTLED"
                    self.pending_payment_cid = ""
                    self.append_audit("Policy decision", "REJECTED BY POLICY")
                    self.refresh_balances()
                    return {
                        "ok": True,
                        "message": "Pending payment rejected",
                        "state": self.to_dict(),
                        "response": {"offline": True},
                    }
                response = mc.submit_command(
                    [mc.reject_command(self.pending_payment_cid, package_ref=self.package_ref)],
                    act_as=[self.owner_party],
                )
                self.mandate_cid = extract_created(response, ":Mandate:Mandate") or self.mandate_cid
                self.transaction_record_cid = extract_created(response, ":Mandate:TransactionRecord") or self.transaction_record_cid
                self.policy_state = "REJECTED BY POLICY"
                self.settlement_state = "NOT SETTLED"
                self.pending_payment_cid = ""
                self.append_audit("Policy decision", "REJECTED BY POLICY")
                self.refresh_balances()
                return {"ok": True, "message": "Pending payment rejected", "state": self.to_dict(), "response": response}
            except Exception as exc:
                return self.set_error(str(exc))


STATE = DemoState()


def html_page(state: dict[str, Any]) -> str:
    state_json = json.dumps(state, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GuardRail Wallet</title>
  <style>
    :root {{
      --bg: #08111d;
      --bg2: #0d1727;
      --panel: rgba(15, 26, 44, 0.92);
      --panel2: rgba(18, 31, 52, 0.95);
      --text: #edf3ff;
      --muted: #9eb0cb;
      --line: rgba(158, 176, 203, 0.16);
      --accent: #66d9ff;
      --accent2: #7ee0b4;
      --warning: #ffd166;
      --danger: #ff7b8f;
      --shadow: 0 18px 60px rgba(0, 0, 0, 0.35);
      --radius: 22px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      font-family: "Trebuchet MS", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 20% 10%, rgba(102, 217, 255, 0.16), transparent 24%),
        radial-gradient(circle at 80% 0%, rgba(126, 224, 180, 0.12), transparent 20%),
        linear-gradient(180deg, var(--bg), var(--bg2));
      min-height: 100vh;
    }}
    .shell {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 28px 20px 40px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 18px;
    }}
    .title {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2rem, 4vw, 3.6rem);
      line-height: 1.02;
      margin: 0 0 8px;
      letter-spacing: 0.01em;
    }}
    .subtitle {{
      margin: 0;
      color: var(--muted);
      font-size: 1.02rem;
      max-width: 760px;
    }}
    .pills {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .pill {{
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.06);
      border: 1px solid var(--line);
      color: var(--text);
      font-size: 0.9rem;
    }}
    .pill.good {{ background: rgba(126, 224, 180, 0.14); color: #b8f7d7; }}
    .pill.warn {{ background: rgba(255, 209, 102, 0.14); color: #ffe7a6; }}
    .pill.bad {{ background: rgba(255, 123, 143, 0.14); color: #ffafbc; }}
    .grid {{
      display: grid;
      grid-template-columns: 1.1fr 1.3fr;
      gap: 16px;
      margin-top: 16px;
    }}
    @media (max-width: 980px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
    .card {{
      background: linear-gradient(180deg, var(--panel), var(--panel2));
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .card h2 {{
      margin: 0 0 10px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.45rem;
    }}
    .card p, .card li {{
      color: var(--muted);
      line-height: 1.45;
    }}
    .balance-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .balance {{
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
    }}
    .balance .label {{ color: var(--muted); font-size: 0.88rem; }}
    .balance .value {{
      margin-top: 6px;
      font-size: clamp(1.4rem, 3vw, 2.15rem);
      font-weight: 700;
    }}
    .value small {{ color: var(--muted); font-weight: 400; }}
    .row {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }}
    .row.three {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    @media (max-width: 760px) {{
      .row, .row.three, .balance-grid {{ grid-template-columns: 1fr; }}
    }}
    label {{
      display: block;
      font-size: 0.86rem;
      color: var(--muted);
      margin: 0 0 5px;
    }}
    input, textarea {{
      width: 100%;
      border: 1px solid var(--line);
      background: rgba(4, 11, 21, 0.65);
      color: var(--text);
      border-radius: 14px;
      padding: 12px 12px;
      outline: none;
      font: inherit;
    }}
    input:focus, textarea:focus {{
      border-color: rgba(102, 217, 255, 0.55);
      box-shadow: 0 0 0 3px rgba(102, 217, 255, 0.12);
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }}
    button {{
      border: 0;
      border-radius: 999px;
      padding: 11px 16px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      background: linear-gradient(180deg, #6bd6ff, #4f9fbf);
      color: #03111d;
    }}
    button.secondary {{
      background: rgba(255,255,255,0.07);
      color: var(--text);
      border: 1px solid var(--line);
    }}
    button.danger {{
      background: linear-gradient(180deg, #ff8b9b, #d85a70);
      color: #1d0810;
    }}
    button:disabled {{
      opacity: 0.5;
      cursor: not-allowed;
    }}
    .state-box {{
      display: grid;
      gap: 10px;
      align-items: start;
    }}
    .state {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(1.65rem, 3.3vw, 2.5rem);
      font-weight: 700;
      letter-spacing: 0.02em;
      margin: 4px 0;
    }}
    .state.auto {{ color: #b8f7d7; }}
    .state.human {{ color: #ffe7a6; }}
    .state.rejected {{ color: #ffafbc; }}
    .state.settled {{ color: #9ff4d0; }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .meta {{
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 14px;
    }}
    .meta .k {{ color: var(--muted); font-size: 0.82rem; }}
    .meta .v {{ margin-top: 4px; font-size: 1rem; word-break: break-word; }}
    .timeline {{
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }}
    .event {{
      display: grid;
      grid-template-columns: 92px 180px 1fr;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--line);
    }}
    @media (max-width: 760px) {{
      .event {{ grid-template-columns: 1fr; }}
    }}
    .event .time {{ color: #a8c5ea; font-family: ui-monospace, SFMono-Regular, monospace; }}
    .event .label {{ font-weight: 700; }}
    .event .detail {{ color: var(--muted); }}
    .section-note {{
      color: var(--muted);
      font-size: 0.94rem;
      margin-top: 6px;
    }}
    .alert {{
      margin-top: 12px;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid rgba(255,255,255,0.12);
      background: rgba(255,255,255,0.05);
      color: var(--text);
      white-space: pre-wrap;
    }}
    .alert.error {{ border-color: rgba(255,123,143,0.35); background: rgba(255,123,143,0.12); }}
    .alert.good {{ border-color: rgba(126,224,180,0.35); background: rgba(126,224,180,0.12); }}
    .hidden {{ display: none !important; }}
    .two-col {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    @media (max-width: 760px) {{
      .two-col {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <div class="hero">
      <div>
        <h1 class="title">GuardRail Wallet</h1>
        <p class="subtitle">Programmable spending controls for autonomous AI agents, with real Canton Coin settlement on DevNet.</p>
      </div>
      <div class="pills">
        <div id="env-pill" class="pill"></div>
        <div id="decision-pill" class="pill"></div>
        <div id="settlement-pill" class="pill"></div>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <h2>1. Wallet Header</h2>
        <p>Live balances for the agent and the vendor. Refresh after settlement to see the real change.</p>
        <div class="balance-grid">
          <div class="balance">
            <div class="label">Agent Wallet</div>
            <div class="value" id="agent-balance">—</div>
            <div class="label" id="agent-party"></div>
          </div>
          <div class="balance">
            <div class="label">Vendor Wallet</div>
            <div class="value" id="vendor-balance">—</div>
            <div class="label" id="vendor-party"></div>
          </div>
        </div>
        <div class="actions">
          <button class="secondary" data-action="refresh-balances">Refresh Balances</button>
        </div>
        <div class="section-note">If DevNet credentials are not configured in this shell, the page still loads but live calls will report an error banner instead of guessing.</div>
      </div>

      <div class="card">
        <h2>2. Policy Configuration</h2>
        <p>Change the threshold here. Payments below the threshold auto-approve. Payments at or above it require human approval.</p>
        <div class="two-col">
          <div>
            <label for="owner_party">Owner Party</label>
            <input id="owner_party" />
          </div>
          <div>
            <label for="spender_party">Spender Party</label>
            <input id="spender_party" />
          </div>
        </div>
        <div class="two-col" style="margin-top: 12px;">
          <div>
            <label for="recipient_party">Vendor / Recipient Party</label>
            <input id="recipient_party" />
          </div>
          <div>
            <label for="preapproval_provider">Preapproval Provider</label>
            <input id="preapproval_provider" placeholder="app_user" />
          </div>
        </div>
        <div class="row three" style="margin-top: 12px;">
          <div>
            <label for="approval_threshold">Approval Threshold (CC)</label>
            <input id="approval_threshold" inputmode="decimal" />
          </div>
          <div>
            <label for="spending_cap">Spending Cap (CC)</label>
            <input id="spending_cap" inputmode="decimal" />
          </div>
          <div>
            <label for="expires_at">Mandate Expiry</label>
            <input id="expires_at" />
          </div>
        </div>
        <div class="section-note" id="policy-explainer"></div>
        <div class="actions">
          <button data-action="configure-demo">Save Demo Settings</button>
          <button data-action="create-mandate">Create / Reset Demo Mandate</button>
          <button class="secondary" data-action="enable-preapproval">Enable Vendor Preapproval</button>
        </div>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <h2>3. Payment Request</h2>
        <p>Submit a small payment for auto-approval or a large payment that pauses for human approval.</p>
        <div class="row three">
          <div>
            <label for="payment_amount">Amount (CC)</label>
            <input id="payment_amount" inputmode="decimal" />
          </div>
          <div>
            <label for="payment_recipient">Recipient</label>
            <input id="payment_recipient" />
          </div>
          <div>
            <label for="payment_purpose">Purpose</label>
            <input id="payment_purpose" />
          </div>
        </div>
        <div class="actions">
          <button data-action="request-payment">Request Payment</button>
        </div>
        <div class="section-note">Scenario 1: `0.10 CC` auto-approves. Scenario 2: `0.50 CC` pauses for approval.</div>
      </div>

      <div class="card">
        <h2>4. Policy Decision</h2>
        <div class="state-box">
          <div id="policy-state" class="state">READY</div>
          <div id="policy-detail" class="section-note"></div>
          <div class="meta-grid">
            <div class="meta"><div class="k">Current Threshold</div><div class="v" id="current-threshold">—</div></div>
            <div class="meta"><div class="k">Current Amount</div><div class="v" id="current-amount">—</div></div>
            <div class="meta"><div class="k">Current Recipient</div><div class="v" id="current-recipient">—</div></div>
            <div class="meta"><div class="k">Settlement Status</div><div class="v" id="current-settlement">WAITING</div></div>
          </div>
        </div>
      </div>
    </div>

    <div class="grid">
      <div class="card" id="approval-card">
        <h2>5. High-Value Approval</h2>
        <p id="approval-copy">This section appears when a payment is waiting on the owner.</p>
        <div class="meta-grid">
          <div class="meta"><div class="k">Amount</div><div class="v" id="approval-amount">—</div></div>
          <div class="meta"><div class="k">Recipient</div><div class="v" id="approval-recipient">—</div></div>
          <div class="meta"><div class="k">Purpose</div><div class="v" id="approval-purpose">—</div></div>
          <div class="meta"><div class="k">Threshold</div><div class="v" id="approval-threshold">—</div></div>
        </div>
        <div class="actions">
          <button data-action="approve-payment">Approve</button>
          <button class="danger" data-action="reject-payment">Reject</button>
        </div>
      </div>

      <div class="card">
        <h2>6. Canton Coin Settlement</h2>
        <p>Approved payments settle through the existing Cantor8 token standard path. If the transfer returns <code>offer</code>, the receiver still needs to accept manually.</p>
        <div class="meta-grid">
          <div class="meta"><div class="k">Transfer Kind</div><div class="v" id="transfer-kind">—</div></div>
          <div class="meta"><div class="k">Instruction CID</div><div class="v" id="instruction-cid">—</div></div>
          <div class="meta"><div class="k">Mandate CID</div><div class="v" id="mandate-cid">—</div></div>
          <div class="meta"><div class="k">Pending CID</div><div class="v" id="pending-cid">—</div></div>
        </div>
        <div class="section-note">Direct settlement is the ideal demo path after vendor preapproval is active.</div>
      </div>
    </div>

    <div class="card">
      <h2>7. Audit Trail</h2>
      <p>Simple timeline of the last actions and results.</p>
      <div id="audit" class="timeline"></div>
    </div>

    <div id="banner" class="alert hidden"></div>
  </div>

  <script>
    window.__STATE__ = {state_json};
  </script>
  <script>
    const state = window.__STATE__;
    const banner = document.getElementById("banner");

    function byId(id) {{
      return document.getElementById(id);
    }}

    function setText(id, value) {{
      const el = byId(id);
      if (!el) return;
      el.textContent = value == null || value === "" ? "—" : value;
    }}

    function showBanner(message, kind) {{
      banner.textContent = message;
      banner.className = "alert " + (kind || "");
      banner.classList.remove("hidden");
    }}

    function clearBanner() {{
      banner.classList.add("hidden");
      banner.textContent = "";
      banner.className = "alert hidden";
    }}

    function render(state) {{
      setText("env-pill", state.environment_state || "DEMO MODE");
      setText("agent-balance", state.agent_balance == null ? "—" : `${{state.agent_balance}} CC`);
      setText("vendor-balance", state.vendor_balance == null ? "—" : `${{state.vendor_balance}} CC`);
      setText("agent-party", state.spender_party || "");
      setText("vendor-party", state.recipient_party || "");

      byId("owner_party").value = state.owner_party || "";
      byId("spender_party").value = state.spender_party || "";
      byId("recipient_party").value = state.recipient_party || "";
      byId("preapproval_provider").value = state.preapproval_provider || "";
      byId("approval_threshold").value = state.approval_threshold || "";
      byId("spending_cap").value = state.spending_cap || "";
      byId("expires_at").value = state.expires_at || "";
      byId("payment_amount").value = state.payment_amount || "";
      byId("payment_recipient").value = state.payment_recipient || "";
      byId("payment_purpose").value = state.payment_purpose || "";

      setText("policy-explainer", `If payment amount < ${{state.approval_threshold}} CC: Auto approve. If payment amount >= ${{state.approval_threshold}} CC: Human approval required.`);
      setText("current-threshold", `${{state.approval_threshold}} CC`);
      setText("current-amount", `${{state.payment_amount}} CC`);
      setText("current-recipient", state.payment_recipient || "—");
      setText("current-settlement", state.settlement_state || "WAITING");
      setText("approval-amount", `${{state.payment_amount}} CC`);
      setText("approval-recipient", state.payment_recipient || "—");
      setText("approval-purpose", state.payment_purpose || "—");
      setText("approval-threshold", `${{state.approval_threshold}} CC`);
      setText("transfer-kind", state.transfer_kind || "—");
      setText("instruction-cid", state.instruction_cid || "—");
      setText("mandate-cid", state.mandate_cid || "—");
      setText("pending-cid", state.pending_payment_cid || "—");
      setText("policy-state", state.policy_state || "READY");
      setText("policy-detail", state.last_error || state.balance_state || "");
      setText("settlement-pill", state.settlement_state || "WAITING");
      setText("decision-pill", state.policy_state || "READY");

      const approvalCard = byId("approval-card");
      const pending = Boolean(state.pending_payment_cid);
      approvalCard.classList.toggle("hidden", !pending && state.policy_state !== "HUMAN APPROVAL REQUIRED");

      const audit = byId("audit");
      audit.innerHTML = "";
      for (const entry of state.audit || []) {{
        const row = document.createElement("div");
        row.className = "event";
        row.innerHTML = `<div class="time">${{entry.time || ""}}</div><div class="label">${{entry.label || ""}}</div><div class="detail">${{entry.detail || ""}}</div>`;
        audit.appendChild(row);
      }}

      const stateEl = byId("policy-state");
      stateEl.classList.remove("auto", "human", "rejected", "settled");
      if ((state.policy_state || "").includes("AUTO")) stateEl.classList.add("auto");
      else if ((state.policy_state || "").includes("HUMAN")) stateEl.classList.add("human");
      else if ((state.policy_state || "").includes("REJECT")) stateEl.classList.add("rejected");
      else if ((state.settlement_state || "") === "DIRECT") stateEl.classList.add("settled");
    }}

    async function api(action, payload) {{
      clearBanner();
      const response = await fetch("/api/action", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ action, payload }})
      }});
      const data = await response.json();
      if (!response.ok || !data.ok) {{
        showBanner(data.error || data.message || `Action failed: ${{action}}`, "error");
      }} else if (data.message) {{
        showBanner(data.message, "good");
      }}
      render(data.state || state);
    }}

    document.querySelectorAll("button[data-action]").forEach((button) => {{
      button.addEventListener("click", async () => {{
        const action = button.dataset.action;
        if (action === "refresh-balances") return api(action, {{}});
        if (action === "configure-demo") {{
          return api(action, {{
            owner_party: byId("owner_party").value,
            spender_party: byId("spender_party").value,
            recipient_party: byId("recipient_party").value,
            preapproval_provider: byId("preapproval_provider").value,
            approval_threshold: byId("approval_threshold").value,
            spending_cap: byId("spending_cap").value,
            expires_at: byId("expires_at").value,
            payment_amount: byId("payment_amount").value,
            payment_recipient: byId("payment_recipient").value,
            payment_purpose: byId("payment_purpose").value,
          }});
        }}
        if (action === "create-mandate") {{
          return api(action, {{
            owner_party: byId("owner_party").value,
            spender_party: byId("spender_party").value,
            recipient_party: byId("recipient_party").value,
            preapproval_provider: byId("preapproval_provider").value,
            approval_threshold: byId("approval_threshold").value,
            spending_cap: byId("spending_cap").value,
            expires_at: byId("expires_at").value,
          }});
        }}
        if (action === "enable-preapproval") {{
          return api(action, {{
            recipient_party: byId("recipient_party").value,
            preapproval_provider: byId("preapproval_provider").value,
          }});
        }}
        if (action === "request-payment") {{
          return api(action, {{
            amount: byId("payment_amount").value,
            recipient: byId("payment_recipient").value,
            purpose: byId("payment_purpose").value,
          }});
        }}
        if (action === "approve-payment" || action === "reject-payment") {{
          return api(action, {{}});
        }}
      }});
    }});

    render(state);
  </script>
</body>
</html>"""


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "GuardRailDemo/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # pragma: no cover - quiet server logs
        return

    def _write_json(self, data: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _write_html(self, content: str) -> None:
        raw = content.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # pragma: no cover - exercised via browser/manual launch
        if self.path == "/" or self.path.startswith("/?"):
            self._write_html(html_page(STATE.to_dict()))
            return
        if self.path == "/api/state":
            self._write_json({"ok": True, "state": STATE.to_dict()})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:  # pragma: no cover - exercised via browser/manual launch
        if self.path != "/api/action":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode() or "{}")
        except json.JSONDecodeError as exc:
            self._write_json({"ok": False, "error": f"Invalid JSON: {exc}", "state": STATE.to_dict()}, status=HTTPStatus.BAD_REQUEST)
            return
        action = payload.get("action")
        action_payload = payload.get("payload") or {}
        if action == "refresh-balances":
            result = STATE.refresh_balances()
        elif action == "configure-demo":
            result = STATE.configure_demo(action_payload)
        elif action == "create-mandate":
            result = STATE.create_demo_mandate()
        elif action == "enable-preapproval":
            result = STATE.enable_preapproval()
        elif action == "request-payment":
            result = STATE.request_payment(action_payload)
        elif action == "approve-payment":
            result = STATE.approve_payment()
        elif action == "reject-payment":
            result = STATE.reject_payment()
        else:
            result = {"ok": False, "error": f"Unknown action: {action}", "state": STATE.to_dict()}
        status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
        self._write_json(result, status=status)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GuardRail Wallet demo UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--offline-demo", action="store_true", help="run a local demo without DevNet calls")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    global STATE
    STATE = DemoState(offline_demo=args.offline_demo)
    if args.offline_demo:
        STATE.agent_balance = Decimal("5.00")
        STATE.vendor_balance = Decimal("0.00")
        STATE.environment_state = "DEMO RECORDING MODE"
        STATE.policy_state = "READY"
        STATE.settlement_state = "WAITING"
        STATE.refresh_balances()
    server = ThreadingHTTPServer((args.host, args.port), DemoHandler)
    print(f"GuardRail Wallet UI running at http://{args.host}:{args.port}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
