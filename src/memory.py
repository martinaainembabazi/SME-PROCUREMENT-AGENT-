"""
Persistent memory for the SME Procurement-Preparation Agent.

Implements the design in:
    docs/requirements/Memory design and data handling note.docx

Storage:
    evidence/memory/approved_supplier_memory.json   (one record per item)
    evidence/memory/memory_log.jsonl                 (read/write audit trail)

Safety rules:
    - Written ONLY after a human approves a draft.
    - Read-only access from the agent during drafting.
    - Advisory only: never finalizes or approves anything.
    - Fails safe: if missing/unreadable/stale, returns None.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = ROOT / "evidence" / "memory"
MEMORY_FILE = MEMORY_DIR / "approved_supplier_memory.json"
LOG_FILE = MEMORY_DIR / "memory_log.jsonl"

STALE_DAYS = 90


@dataclass
class MemoryRecord:
    item_code: str
    item_name: str
    approved_supplier: str
    approved_unit_price_ugx: float
    approved_quantity: int
    source_draft_id: str
    approved_by: str
    approved_at: str  # ISO 8601

    def is_stale(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        try:
            approved_at = datetime.fromisoformat(self.approved_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        return (now - approved_at) > timedelta(days=STALE_DAYS)


class MemoryStore:
    """Read/write access to approved-supplier memory."""

    def __init__(self, memory_dir: Path | None = None):
        self.memory_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
        self.memory_file = self.memory_dir / "approved_supplier_memory.json"
        self.log_file = self.memory_dir / "memory_log.jsonl"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    # ---------------- read ----------------

    def get_approved_supplier(self, item_code: str) -> MemoryRecord | None:
        """Return the approved supplier record for item_code, or None.

        Returns None if:
            - memory file is missing or unreadable
            - no record exists for this item_code
            - the record is stale (>90 days)

        Logs the read to memory_log.jsonl.
        """
        record = self._load().get(item_code)
        if record is None:
            self._log("read_miss", item_code=item_code, detail="no_record")
            return None

        if record.is_stale():
            self._log("read_stale", item_code=item_code,
                      detail=f"approved_at={record.approved_at}")
            return None

        self._log("read_hit", item_code=item_code,
                  detail=f"supplier={record.approved_supplier}")
        return record

    # ---------------- write ----------------

    def record_approval(
        self,
        item_code: str,
        item_name: str,
        approved_supplier: str,
        approved_unit_price_ugx: float,
        approved_quantity: int,
        source_draft_id: str,
        approved_by: str,
        approved_at: str | None = None,
    ) -> MemoryRecord:
        """Write a new approval record. Called ONLY by the orchestration layer
        after a human explicitly approves a draft."""
        record = MemoryRecord(
            item_code=item_code,
            item_name=item_name,
            approved_supplier=approved_supplier,
            approved_unit_price_ugx=float(approved_unit_price_ugx),
            approved_quantity=int(approved_quantity),
            source_draft_id=source_draft_id,
            approved_by=approved_by,
            approved_at=approved_at or datetime.now(timezone.utc).isoformat(),
        )
        data = self._load()
        data[item_code] = record
        self._save(data)
        self._log("write", item_code=item_code,
                  detail=f"supplier={approved_supplier} draft={source_draft_id} by={approved_by}")
        return record

    def forget(self, item_code: str) -> bool:
        """Delete one record (admin action)."""
        data = self._load()
        if item_code in data:
            del data[item_code]
            self._save(data)
            self._log("delete", item_code=item_code, detail="record_removed")
            return True
        return False

    def forget_all(self) -> None:
        """Delete the entire memory file (admin action)."""
        if self.memory_file.exists():
            self.memory_file.unlink()
        self._log("delete_all", item_code="*", detail="memory_file_removed")

    # ---------------- internal ----------------

    def _load(self) -> dict[str, MemoryRecord]:
        if not self.memory_file.exists():
            return {}
        try:
            raw: dict[str, Any] = json.loads(self.memory_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._log("read_error", item_code="*", detail="memory_file_unreadable")
            return {}
        return {k: MemoryRecord(**v) for k, v in raw.items()}

    def _save(self, data: dict[str, MemoryRecord]) -> None:
        payload = {k: asdict(v) for k, v in data.items()}
        self.memory_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _log(self, event: str, item_code: str, detail: str) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "item_code": item_code,
            "detail": detail,
        }
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


# ---------------- CLI ----------------

def _cli():
    import sys
    store = MemoryStore()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"

    if cmd == "show":
        data = store._load()
        if not data:
            print("(memory empty)")
        for code, rec in data.items():
            stale = " [STALE]" if rec.is_stale() else ""
            print(f"{code}: {rec.approved_supplier}  approved_by={rec.approved_by}  at={rec.approved_at}{stale}")
    elif cmd == "forget" and len(sys.argv) > 2:
        ok = store.forget(sys.argv[2])
        print("removed" if ok else "not found")
    elif cmd == "forget-all":
        store.forget_all()
        print("memory cleared")
    else:
        print("Usage: python src/memory.py [show | forget <item_code> | forget-all]")


if __name__ == "__main__":
    _cli()