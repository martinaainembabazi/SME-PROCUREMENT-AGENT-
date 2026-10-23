"""Requisition lifecycle for the web app: draft -> approved/rejected -> received.

The agent can only create drafts (via orchestration.py). Every later step is a
human action performed here, with the rules from knowledge/policies/:

- A quote from the chosen supplier must exist for the item.
- The supplier must have payment terms on file.
- The quantity must meet the supplier's MOQ.
- Totals at or above UGX 2,000,000 need the Business Owner (auth.can_approve_amount).
- Only approvals are written to supplier memory (memory_store.ApprovedSupplierMemory).
"""

from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from auth import ROLES, can, can_approve_amount
from data_store import InventoryStore, QuoteStore, normalize_supplier
from memory_store import ApprovedSupplierMemory
from orchestration import AppToolOrchestrator

ROOT = Path(__file__).resolve().parent.parent

STATUS_LABELS = {
    "pending_human_approval": "Pending approval",
    "approved": "Approved",
    "rejected": "Rejected",
    "received": "Received",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _actor(user: dict[str, Any]) -> str:
    return f"{user['full_name']} ({ROLES[user['role']]})"


class RequisitionService:
    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else ROOT
        self.drafts_dir = self.base_dir / "evidence" / "drafts"
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.inventory = InventoryStore(self.base_dir)
        self.quotes = QuoteStore(self.base_dir)
        self.memory = ApprovedSupplierMemory(self.base_dir)
        self.orchestrator = AppToolOrchestrator(self.base_dir)

    # ------------------------------------------------------------------ read
    def _path(self, draft_id: str) -> Path:
        draft_id = str(draft_id or "").strip()
        if not draft_id or any(c in draft_id for c in "/\\.") or len(draft_id) > 80:
            raise ValueError("Invalid requisition id.")
        return self.drafts_dir / f"{draft_id}.json"

    def get(self, draft_id: str) -> dict[str, Any]:
        path = self._path(draft_id)
        if not path.exists():
            raise ValueError(f"Requisition {draft_id} was not found.")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, record: dict[str, Any]) -> None:
        _atomic_write(self._path(record["draft_id"]), json.dumps(record, indent=2))

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        records = []
        for path in self.drafts_dir.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict) or not record.get("draft_id"):
                continue
            if status and record.get("status") != status:
                continue
            records.append(record)
        records.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
        return records

    def evaluate(self, record: dict[str, Any]) -> dict[str, Any]:
        """Price the requisition from current quotes and list any policy problems."""
        issues: list[str] = []
        item_code = str(record.get("item_code", "")).upper()
        quantity = record.get("quantity")
        if self.inventory.get_item(item_code) is None:
            issues.append(f"Item {item_code} is not in the stock register.")

        quote = None
        try:
            quote = self.quotes.get_quote(item_code, record.get("supplier_name", ""))
        except ValueError:
            pass
        unit_price = total = None
        if quote is None:
            issues.append(f"No quote on file from supplier {record.get('supplier_name')} for {item_code}.")
        else:
            unit_price = float(quote["price_ugx"])
            if isinstance(quantity, int):
                total = unit_price * quantity
            if not str(quote.get("payment_terms", "")).strip():
                issues.append("Supplier has no confirmed payment terms on file.")
            moq = quote.get("moq")
            if isinstance(moq, int) and isinstance(quantity, int) and quantity < moq:
                issues.append(f"Quantity {quantity} is below the supplier's MOQ of {moq}.")

        if record.get("approved_total_ugx") is not None:
            total = record["approved_total_ugx"]
            unit_price = record.get("approved_unit_price_ugx", unit_price)
        return {
            "unit_price_ugx": unit_price,
            "total_ugx": total,
            "quote": quote,
            "issues": issues,
            "needs_owner": total is not None and total >= 2_000_000,
        }

    # ----------------------------------------------------------------- write
    def create_manual(self, user: dict[str, Any], item_code: str, quantity: int,
                      supplier_name: str, notes: str = "") -> dict[str, Any]:
        if not can(user, "create_draft"):
            raise PermissionError("Your role cannot create requisitions.")
        supplier = f"Supplier {normalize_supplier(supplier_name)}"
        # Drafting is the same low-risk action the agent performs, so it goes
        # through the same guarded tool and lands in the same pending state.
        result = self.orchestrator.call_tool(
            "create_draft_requisition",
            {"item_code": item_code, "quantity": quantity, "supplier_name": supplier, "notes": notes},
            principal="agent",
        )
        record = result["record"]
        record.update({"source": "manual", "created_by": _actor(user)})
        self._save(record)
        return record

    def approve(self, user: dict[str, Any], draft_id: str) -> dict[str, Any]:
        if not can(user, "approve"):
            raise PermissionError("Your role cannot approve requisitions.")
        record = self.get(draft_id)
        if record.get("status") != "pending_human_approval":
            raise ValueError(f"Requisition {draft_id} is not pending approval.")
        evaluation = self.evaluate(record)
        if evaluation["issues"]:
            raise ValueError("Cannot approve: " + " ".join(evaluation["issues"]))
        allowed, reason = can_approve_amount(user, evaluation["total_ugx"])
        if not allowed:
            raise PermissionError(reason)

        self.memory.record_approval(draft_id, _actor(user), evaluation["unit_price_ugx"])
        record = self.get(draft_id)
        record.update({
            "approved_by_username": user["username"],
            "approved_unit_price_ugx": evaluation["unit_price_ugx"],
            "approved_total_ugx": evaluation["total_ugx"],
            "payment_terms": evaluation["quote"].get("payment_terms"),
            "lead_time_days": evaluation["quote"].get("lead_time_days"),
        })
        self._save(record)
        return record

    def reject(self, user: dict[str, Any], draft_id: str, reason: str) -> dict[str, Any]:
        if not can(user, "reject"):
            raise PermissionError("Your role cannot reject requisitions.")
        reason = " ".join(str(reason or "").split())
        if not reason:
            raise ValueError("A rejection reason is required.")
        self.memory.record_rejection(draft_id, _actor(user), reason[:500])
        record = self.get(draft_id)
        record["rejected_by_username"] = user["username"]
        self._save(record)
        return record

    def receive(self, user: dict[str, Any], draft_id: str, received_qty: int) -> dict[str, Any]:
        if not can(user, "receive_goods"):
            raise PermissionError("Your role cannot record deliveries.")
        record = self.get(draft_id)
        if record.get("status") != "approved":
            raise ValueError("Only approved requisitions can be received.")
        item = self.inventory.receive_stock(record["item_code"], received_qty)
        record.update({
            "status": "received",
            "received_qty": int(received_qty),
            "received_by": _actor(user),
            "received_at": _now(),
            "stock_after_receipt": item["current_qty"],
        })
        self._save(record)
        return record

    # ---------------------------------------------------------------- export
    def export_csv(self, record: dict[str, Any]) -> str:
        evaluation = self.evaluate(record)
        fields = [
            ("Requisition ID", record.get("draft_id")),
            ("Status", STATUS_LABELS.get(record.get("status"), record.get("status"))),
            ("Item code", record.get("item_code")),
            ("Item name", record.get("item_name")),
            ("Quantity", record.get("quantity")),
            ("Supplier", record.get("supplier_name")),
            ("Unit price (UGX)", evaluation["unit_price_ugx"]),
            ("Total (UGX)", evaluation["total_ugx"]),
            ("Payment terms", (evaluation["quote"] or {}).get("payment_terms", record.get("payment_terms"))),
            ("Lead time (days)", (evaluation["quote"] or {}).get("lead_time_days", record.get("lead_time_days"))),
            ("Notes", record.get("notes")),
            ("Created at", record.get("created_at")),
            ("Created by", record.get("created_by", "Agent")),
            ("Approved by", record.get("approved_by")),
            ("Approved at", record.get("approved_at")),
            ("Received at", record.get("received_at")),
        ]
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(["Field", "Value"])
        writer.writerows((k, "" if v is None else v) for k, v in fields)
        return buffer.getvalue()
