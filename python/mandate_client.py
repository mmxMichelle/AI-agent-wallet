#!/usr/bin/env python3
"""Minimal DevNet client for the Mandate Daml package."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request
import uuid
from typing import Any, Iterable, Optional, Sequence


ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import c8lab  # noqa: E402


DEFAULT_PACKAGE_REF = "#daml-starter-0.0.1"
DEFAULT_DAR_PATH = ROOT / "daml-starter" / ".daml" / "dist" / "daml-starter-0.0.1.dar"
PACKAGE_ID_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class MandateClientError(c8lab.LabError):
    """A client-side or API-side Mandate error."""


def mandate_template_id(entity_name: str, package_ref: str = DEFAULT_PACKAGE_REF) -> str:
    package_ref = package_ref.strip()
    if not package_ref:
        raise MandateClientError("package_ref must not be empty")
    if not package_ref.startswith("#") and not PACKAGE_ID_RE.fullmatch(package_ref):
        package_ref = f"#{package_ref}"
    return f"{package_ref}:Mandate:{entity_name}"


def create_proposal_command(
    owner: str,
    spender: str,
    allowed_recipient: str,
    cap: str | float | int,
    approval_threshold: str | float | int,
    expires_at: str,
    package_ref: str = DEFAULT_PACKAGE_REF,
) -> dict[str, Any]:
    return {
        "CreateCommand": {
            "templateId": mandate_template_id("MandateProposal", package_ref=package_ref),
            "createArguments": {
                "owner": owner,
                "spender": spender,
                "allowedRecipient": allowed_recipient,
                "approvalThreshold": str(approval_threshold),
                "cap": str(cap),
                "expiresAt": expires_at,
            },
        }
    }


def accept_proposal_command(
    proposal_cid: str,
    package_ref: str = DEFAULT_PACKAGE_REF,
) -> dict[str, Any]:
    return {
        "ExerciseCommand": {
            "templateId": mandate_template_id("MandateProposal", package_ref=package_ref),
            "contractId": proposal_cid,
            "choice": "Accept",
            "choiceArgument": {},
        }
    }


def request_high_value_command(
    mandate_cid: str,
    amount: str | float | int,
    recipient: str,
    purpose: str,
    package_ref: str = DEFAULT_PACKAGE_REF,
) -> dict[str, Any]:
    return {
        "ExerciseCommand": {
            "templateId": mandate_template_id("Mandate", package_ref=package_ref),
            "contractId": mandate_cid,
            "choice": "RequestHighValue",
            "choiceArgument": {
                "amount": str(amount),
                "recipient": recipient,
                "purpose": purpose,
            },
        }
    }


def approve_command(
    pending_cid: str,
    package_ref: str = DEFAULT_PACKAGE_REF,
) -> dict[str, Any]:
    return {
        "ExerciseCommand": {
            "templateId": mandate_template_id("PendingPayment", package_ref=package_ref),
            "contractId": pending_cid,
            "choice": "Approve",
            "choiceArgument": {},
        }
    }


def reject_command(
    pending_cid: str,
    package_ref: str = DEFAULT_PACKAGE_REF,
) -> dict[str, Any]:
    return {
        "ExerciseCommand": {
            "templateId": mandate_template_id("PendingPayment", package_ref=package_ref),
            "contractId": pending_cid,
            "choice": "Reject",
            "choiceArgument": {},
        }
    }


def _command_request(commands: Sequence[dict[str, Any]], act_as: Sequence[str], user_id: str) -> dict[str, Any]:
    return {
        "commands": list(commands),
        "commandId": f"mandate-{uuid.uuid4()}",
        "actAs": list(act_as),
        "userId": user_id,
    }


def submit_command(
    commands: Sequence[dict[str, Any]],
    act_as: Sequence[str],
    sub: str | None = None,
    disclosed: Optional[Sequence[dict[str, Any]]] = None,
    want_transaction: bool = True,
) -> dict[str, Any]:
    user_id = sub or c8lab.USER
    body = _command_request(commands, act_as, user_id)
    if disclosed:
        body["disclosedContracts"] = list(disclosed)
    return c8lab.submit(
        body["commands"],
        act_as=list(act_as),
        sub=user_id,
        disclosed=list(disclosed) if disclosed else None,
        command_id=body["commandId"],
        want_transaction=want_transaction,
    )


def _find_created_contract_ids(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_find_created_contract_ids(item))
        return found
    if not isinstance(node, dict):
        return found

    created = None
    for key in ("CreatedTreeEvent", "CreatedEvent", "createdEvent", "created_event"):
        if key in node:
            created = node[key]
            break
    if isinstance(created, dict):
        contract_id = created.get("contractId") or created.get("contract_id")
        if contract_id:
            found.append(str(contract_id))

    for value in node.values():
        found.extend(_find_created_contract_ids(value))
    return found


def _extract_created_contract_id(response: dict[str, Any], template_suffix: str) -> Optional[str]:
    for cid in _find_created_contract_ids(response):
        if template_suffix in cid:
            return cid
    return None


def upload_dar(dar_path: str | pathlib.Path,
               vet_all_packages: bool = True,
               synchronizer_id: Optional[str] = None) -> dict[str, Any]:
    dar_bytes = pathlib.Path(dar_path).read_bytes()
    if not dar_bytes:
        raise MandateClientError(f"DAR file is empty: {dar_path}")

    query: list[tuple[str, str]] = []
    if vet_all_packages:
        query.append(("vetAllPackages", "true"))
    if synchronizer_id:
        query.append(("synchronizerId", synchronizer_id))
    suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
    url = c8lab.BASE.rstrip("/") + "/v2/packages" + suffix
    req = urllib.request.Request(
        url,
        data=dar_bytes,
        method="POST",
        headers={
            "Authorization": f"Bearer {c8lab.token()}",
            "Content-Type": "application/octet-stream",
        },
    )
    try:
        raw = urllib.request.urlopen(req, timeout=120).read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:1200]
        raise MandateClientError(f"HTTP {e.code} from {url}\n  {detail}") from e
    except urllib.error.URLError as e:
        raise MandateClientError(f"cannot reach {url}: {e.reason}") from e
    return json.loads(raw or b"{}")


def list_packages() -> dict[str, Any]:
    return c8lab.call("/v2/packages")


def list_local_parties() -> list[str]:
    return c8lab.local_parties()


def settle_payment(from_party: str, to_party: str, amount: str | float | int) -> dict[str, Any]:
    holdings = c8lab.holdings(from_party)
    if not holdings:
        raise MandateClientError(
            "Sender has no Canton Coin holdings; fund this party before settlement."
        )
    return c8lab.transfer(from_party, to_party, amount)


def print_settlement_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, indent=2, sort_keys=True))
    transfer_kind = result.get("transferKind")
    print(f"\ntransferKind: {transfer_kind}")
    if transfer_kind == "direct":
        print("Settlement completed immediately.")
    elif transfer_kind == "offer":
        instruction_cid = result.get("instructionCid")
        if instruction_cid:
            print(f"Instruction CID: {instruction_cid}")
        print("Next step:")
        print(f"  python3 c8lab.py accept {instruction_cid} <to-party>")


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal Mandate DevNet client")
    parser.add_argument(
        "--package-ref",
        default=DEFAULT_PACKAGE_REF,
        help="package reference for Mandate templates (default: #daml-starter-0.0.1)",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help="Ledger API user id to submit as (default: c8lab.USER)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("parties", help="show local parties")
    sub.add_parser("packages", help="list uploaded packages")

    p = sub.add_parser("upload-dar", help="upload a DAR to the participant")
    p.add_argument("--dar", default=str(DEFAULT_DAR_PATH))
    p.add_argument("--no-vet-all-packages", action="store_true")
    p.add_argument("--synchronizer-id", default=None)

    p = sub.add_parser("create-proposal", help="create a MandateProposal")
    p.add_argument("--owner", required=True)
    p.add_argument("--spender", required=True)
    p.add_argument("--allowed-recipient", required=True)
    p.add_argument("--cap", required=True)
    p.add_argument("--approval-threshold", required=True)
    p.add_argument("--expires-at", required=True)

    p = sub.add_parser("accept-proposal", help="accept a MandateProposal")
    p.add_argument("--spender", required=True)
    p.add_argument("--proposal-cid", required=True)

    p = sub.add_parser("request-high-value", help="request owner approval")
    p.add_argument("--spender", required=True)
    p.add_argument("--mandate-cid", required=True)
    p.add_argument("--amount", required=True)
    p.add_argument("--recipient", required=True)
    p.add_argument("--purpose", required=True)

    p = sub.add_parser("approve", help="approve a PendingPayment")
    p.add_argument("--owner", required=True)
    p.add_argument("--pending-cid", required=True)

    p = sub.add_parser("reject", help="reject a PendingPayment")
    p.add_argument("--owner", required=True)
    p.add_argument("--pending-cid", required=True)

    p = sub.add_parser("settle", help="settle an approved Mandate payment")
    p.add_argument("--from-party", required=True)
    p.add_argument("--to-party", required=True)
    p.add_argument("--amount", required=True)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    user_id = args.user_id or c8lab.USER
    package_ref = args.package_ref

    try:
        if args.cmd == "parties":
            _print_json(list_local_parties())
        elif args.cmd == "packages":
            _print_json(list_packages())
        elif args.cmd == "upload-dar":
            out = upload_dar(
                args.dar,
                vet_all_packages=not args.no_vet_all_packages,
                synchronizer_id=args.synchronizer_id,
            )
            _print_json(out)
        elif args.cmd == "create-proposal":
            out = submit_command(
                [create_proposal_command(
                    args.owner,
                    args.spender,
                    args.allowed_recipient,
                    args.cap,
                    args.approval_threshold,
                    args.expires_at,
                    package_ref=package_ref,
                )],
                act_as=[args.owner],
                sub=user_id,
                want_transaction=True,
            )
            _print_json(out)
        elif args.cmd == "accept-proposal":
            out = submit_command(
                [accept_proposal_command(args.proposal_cid, package_ref=package_ref)],
                act_as=[args.spender],
                sub=user_id,
                want_transaction=True,
            )
            _print_json(out)
        elif args.cmd == "request-high-value":
            out = submit_command(
                [request_high_value_command(
                    args.mandate_cid,
                    args.amount,
                    args.recipient,
                    args.purpose,
                    package_ref=package_ref,
                )],
                act_as=[args.spender],
                sub=user_id,
                want_transaction=True,
            )
            _print_json(out)
        elif args.cmd == "approve":
            out = submit_command(
                [approve_command(args.pending_cid, package_ref=package_ref)],
                act_as=[args.owner],
                sub=user_id,
                want_transaction=True,
            )
            _print_json(out)
        elif args.cmd == "reject":
            out = submit_command(
                [reject_command(args.pending_cid, package_ref=package_ref)],
                act_as=[args.owner],
                sub=user_id,
                want_transaction=True,
            )
            _print_json(out)
        elif args.cmd == "settle":
            out = settle_payment(args.from_party, args.to_party, args.amount)
            print_settlement_result(out)
        else:  # pragma: no cover - argparse enforces commands
            raise MandateClientError(f"unknown command: {args.cmd}")
    except c8lab.LabError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
