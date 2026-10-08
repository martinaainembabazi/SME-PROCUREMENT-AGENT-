"""Persistent memory for the SME Procurement agent: approved supplier preferences.

Rules (from the Memory Design and Data Handling Note):
- Written ONLY by record_approval(), after a named human approves a pending draft.
- Rejected or pending drafts never reach memory.
- Read through lookup(), a read-only call made at the drafting step.
- Read problems never raise: the agent drafts normally and reports that no preference was applied.
- Every read, write, skipped write and delete is logged to memory_log.jsonl.
- Stored content is data only; it is never executed or followed as an instruction.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STALE_AFTER_DAYS = 90  # PLACEHOLDER: agree the real [N] with the team, then update the note


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class ApprovedSupplierMemory:
    """One JSON file, one record per item_code."""

    def __init__(self, base_dir: str | Path | None = None, stale_after_days: int = STALE_AFTER_DAYS):
        self.base_dir = Path(base_dir) if base_dir is not None else ROOT
        self.memory_dir = self.base_dir / "evidence" / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.memory_dir / "approved_supplier_memory.json"
        self.log_path = self.memory_dir / "memory_log.jsonl"
        self.drafts_dir = self.base_dir / "evidence" / "drafts"
        self.stale_after = timedelta(days=stale_after_days)

    # ------------------------------------------------------------------ helpers
    def _log(self, event: str, **fields: Any) -> None:
        entry = {"ts": _now().isoformat(), "event": event, **fields}
        try:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        except OSError:
            pass  # logging must never break the workflow

    def _load(self) -> tuple[dict[str, Any], str | None]:
        """Return (records, error). A missing file is an empty store, not an error."""
        if not self.path.exists():
            return {}, None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}, "unreadable"
        if not isinstance(data, dict):
            return {}, "unreadable"
        return data, None

    def _load_pending_draft(self, draft_id: str) -> tuple[Path, dict[str, Any]]:
        draft_path = self.drafts_dir / f"{draft_id}.json"
        if not draft_path.exists():
            raise FileNotFoundError(f"Draft not found: {draft_path}")
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        if draft.get("status") != "pending_human_approval":
            raise ValueError(f"Draft {draft_id} is '{draft.get('status')}'; only pending drafts can be decided.")
        return draft_path, draft

    # --------------------------------------------------------------------- read
    def lookup(self, item_code: str) -> dict[str, Any]:
        """Read-only lookup. status is one of: found, stale, no_record, memory_unavailable."""
        key = str(item_code or "").strip().upper()
        records, error = self._load()
        if error:
            self._log("memory_read", item_code=key, outcome="memory_unavailable")
            return {"status": "memory_unavailable", "item_code": key, "record": None, "label": None}

        record = records.get(key)
        if not isinstance(record, dict):
            self._log("memory_read", item_code=key, outcome="no_record")
            return {"status": "no_record", "item_code": key, "record": None, "label": None}

        try:
            approved_at = datetime.fromisoformat(record["approved_at"])
            if approved_at.tzinfo is None:
                approved_at = approved_at.replace(tzinfo=timezone.utc)
            stale = _now() - approved_at > self.stale_after
        except (KeyError, TypeError, ValueError):
            stale = True  # cannot verify age, so do not trust it

        status = "stale" if stale else "found"
        label = f"last approved on {str(record.get('approved_at', ''))[:10]}, draft {record.get('source_draft_id', 'unknown')}"
        self._log("memory_read", item_code=key, outcome=status, record_id=record.get("source_draft_id"))
        return {"status": status, "item_code": key, "record": record, "label": label}

    # -------------------------------------------------------------------- write
    def record_approval(self, draft_id: str, approved_by: str, approved_unit_price_ugx: float | None = None) -> dict[str, Any]:
        """The ONLY path that writes memory. Call it when a named human approves a pending draft."""
        if not approved_by or not str(approved_by).strip():
            raise ValueError("approved_by is required: memory is only written after a named human approval.")

        draft_path, draft = self._load_pending_draft(draft_id)
        approved_at = _now().isoformat()
        draft.update({"status": "approved", "approved_by": str(approved_by).strip(), "approved_at": approved_at})
        _atomic_write(draft_path, json.dumps(draft, indent=2))

        key = str(draft["item_code"]).strip().upper()
        record = {
            "item_code": key,
            "item_name": draft.get("item_name", key),
            "approved_supplier": draft["supplier_name"],
            "approved_quantity": draft["quantity"],
            "approved_unit_price_ugx": approved_unit_price_ugx,
            "source_draft_id": draft_id,
            "approved_by": str(approved_by).strip(),
            "approved_at": approved_at,
        }

        records, error = self._load()
        if error:
            backup = self.path.with_name(self.path.name + ".corrupt.bak")
            os.replace(self.path, backup)
            self._log("memory_file_unreadable_backed_up", backup=str(backup))
            records = {}

        records[key] = record  # a newer approval replaces the old record
        _atomic_write(self.path, json.dumps(records, indent=2))
        self._log("memory_write", item_code=key, record_id=draft_id, approved_by=record["approved_by"])
        return {"memory_written": True, "record": record, "path": str(self.path)}

    def record_rejection(self, draft_id: str, rejected_by: str, reason: str = "") -> dict[str, Any]:
        """Mark a draft rejected. Memory is deliberately NOT touched; the skipped write is logged."""
        if not rejected_by or not str(rejected_by).strip():
            raise ValueError("rejected_by is required.")

        draft_path, draft = self._load_pending_draft(draft_id)
        draft.update({
            "status": "rejected",
            "rejected_by": str(rejected_by).strip(),
            "rejected_at": _now().isoformat(),
            "rejection_reason": reason,
        })
        _atomic_write(draft_path, json.dumps(draft, indent=2))
        self._log("memory_write_skipped", item_code=str(draft.get("item_code", "")).upper(), record_id=draft_id, reason="draft_rejected")
        return {"memory_written": False, "draft_status": "rejected"}

    # ------------------------------------------------------------------- delete
    def delete(self, item_code: str, requested_by: str) -> dict[str, Any]:
        """Human-initiated removal of one record."""
        if not requested_by or not str(requested_by).strip():
            raise ValueError("requested_by is required: deletion is a human action.")
        records, error = self._load()
        if error:
            raise RuntimeError("Memory file is unreadable; repair or restore it before deleting records.")

        key = str(item_code or "").strip().upper()
        if records.pop(key, None) is None:
            self._log("memory_delete", item_code=key, outcome="no_record", requested_by=requested_by)
            return {"deleted": False}
        _atomic_write(self.path, json.dumps(records, indent=2))
        self._log("memory_delete", item_code=key, outcome="deleted", requested_by=requested_by)
        return {"deleted": True}


def prepare_draft_context(orchestrator: Any, memory: ApprovedSupplierMemory, item_code: str) -> dict[str, Any]:
    """Build what the drafting step shows the human.

    Order matters: live quotes are fetched FIRST, then memory is read. Memory only ever
    contributes a labelled suggestion. The tool's own 'recommendation' block is ignored so
    the agent never declares a final supplier (Prompt Specification Constraint 3).
    """
    context: dict[str, Any] = {
        "item_code": str(item_code).strip().upper(),
        "live_quotes": [],
        "live_quotes_error": None,
        "memory_status": None,
        "prefill_supplier": None,
        "flags": [],
        "requires_human_decision": True,
    }

    try:
        result = orchestrator.call_tool("compare_supplier_quotes", {"item_code": item_code})
        context["live_quotes"] = result.get("quotes", [])
    except Exception as exc:  # tool failure is surfaced, never papered over
        context["live_quotes_error"] = f"{type(exc).__name__}: {exc}"
        context["flags"].append("live_quotes_unavailable")

    mem = memory.lookup(item_code)
    context["memory_status"] = mem["status"]
    quotes = context["live_quotes"]

    if mem["status"] == "found":
        remembered = mem["record"]["approved_supplier"]
        context["prefill_supplier"] = {"supplier": remembered, "label": mem["label"], "source": "memory"}
        if not quotes:
            context["flags"].append("no_live_quotes_to_verify_preference")
        else:
            match = next((q for q in quotes if q.get("supplier") == remembered), None)
            if match is None:
                context["flags"].append("remembered_supplier_not_in_current_quotes")
            else:
                best = quotes[0]
                key = lambda q: (q.get("price_ugx", float("inf")), q.get("lead_time_days", float("inf")))
                if best.get("supplier") != remembered and key(best) < key(match):
                    context["flags"].append("cheaper_or_faster_quote_available")
    elif mem["status"] == "stale":
        context["flags"].append("memory_record_stale_not_prefilled")
    elif mem["status"] == "memory_unavailable":
        context["flags"].append("memory_unavailable_no_preference_applied")
    else:
        context["flags"].append("no_preference_found")

    return context
