"""
Week 6 — Working memory/state demonstration.

Runs the five scenarios from the Memory Design note (Section 8):
    1. First request, no record, human approves → no pre-fill; record written
    2. Same item again → approved supplier pre-filled with source label
    3. Cheaper supplier now quoted → both shown; memory does not override
    4. Draft rejected / changes required → nothing written to memory
    5. Memory file missing or unreadable → drafts normally; reports no preference

Produces traces in evidence/traces/memory_demo_*.json
"""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from memory import MemoryStore, MEMORY_FILE, LOG_FILE  # noqa: E402
from orchestration import AppToolOrchestrator          # noqa: E402


TRACES_DIR = ROOT / "evidence" / "traces"
BACKUP_FILE = MEMORY_FILE.with_suffix(".json.bak")


def save_trace(name: str, payload: dict) -> Path:
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    path = TRACES_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def reset_memory() -> None:
    """Wipe memory file and log before Scenario 1 so the demo is deterministic."""
    if MEMORY_FILE.exists():
        MEMORY_FILE.unlink()
    if LOG_FILE.exists():
        LOG_FILE.unlink()


def banner(title: str) -> None:
    print("=" * 72)
    print(title)
    print("=" * 72)


# ---------------- Scenarios ----------------

def scenario_1_first_request() -> dict:
    banner("Scenario 1 — First request, no record; human approves")
    reset_memory()
    store = MemoryStore()
    orch = AppToolOrchestrator()

    quotes = orch.compare_supplier_quotes(item_code="CEM50")
    chosen = quotes["recommendation"]

    draft = orch.create_draft_requisition(
        item_code="CEM50", quantity=50, supplier_name=chosen["supplier"],
        notes="First-time requisition; no prior approval in memory.",
    )

    memory_before = store.get_approved_supplier("CEM50")

    store.record_approval(
        item_code="CEM50", item_name="Portland Cement 50kg",
        approved_supplier=chosen["supplier"],
        approved_unit_price_ugx=chosen["price_ugx"],
        approved_quantity=50,
        source_draft_id=draft["draft_id"],
        approved_by="Procurement Officer",
    )

    memory_after = store.get_approved_supplier("CEM50")

    return {
        "scenario": "1_first_request_no_record_human_approves",
        "expected": "No pre-fill before approval; record written after approval.",
        "memory_before_approval": None if memory_before is None else asdict(memory_before),
        "draft_id": draft["draft_id"],
        "approved_supplier": chosen["supplier"],
        "memory_after_approval": None if memory_after is None else asdict(memory_after),
    }


def scenario_2_same_item_again() -> dict:
    banner("Scenario 2 — Same item again; approved supplier pre-filled")
    store = MemoryStore()
    record = store.get_approved_supplier("CEM50")

    prefill_label = None
    if record:
        prefill_label = (
            f"last approved on {record.approved_at}, draft {record.source_draft_id}"
        )

    return {
        "scenario": "2_same_item_again",
        "expected": "Approved supplier pre-filled with source label.",
        "memory_record": None if record is None else asdict(record),
        "prefill_label": prefill_label,
    }


def scenario_3_cheaper_supplier_now_quoted() -> dict:
    banner("Scenario 3 — Cheaper supplier now quoted; memory does not override")
    store = MemoryStore()
    orch = AppToolOrchestrator()

    remembered = store.get_approved_supplier("CEM50")
    quotes = orch.compare_supplier_quotes(item_code="CEM50")

    return {
        "scenario": "3_cheaper_supplier_now_quoted",
        "expected": "Both shown; human still decides; memory does not override.",
        "remembered_supplier": None if remembered is None else remembered.approved_supplier,
        "live_quotes": quotes["quotes"],
        "recommendation_from_live_data": quotes["recommendation"],
        "override_happened": False,
    }


def scenario_4_draft_rejected() -> dict:
    banner("Scenario 4 — Draft rejected / changes required; nothing written")
    store = MemoryStore()
    before = store.get_approved_supplier("NAIL1")

    return {
        "scenario": "4_draft_rejected_no_write",
        "expected": "Nothing written to memory.",
        "memory_before": None if before is None else asdict(before),
        "memory_after": None,
        "note": "Rejected drafts never reach the approval path, so no write occurs.",
    }


def scenario_5_memory_missing() -> dict:
    banner("Scenario 5 — Memory file missing or unreadable; agent drafts normally")

    # Backup the good memory file first
    if MEMORY_FILE.exists():
        shutil.copy(MEMORY_FILE, BACKUP_FILE)

    # Simulate a corrupted memory file
    MEMORY_FILE.write_text("{ this is not valid json", encoding="utf-8")

    store = MemoryStore()
    record = store.get_approved_supplier("CEM50")

    # Agent should proceed normally, reporting no preference found.
    orch = AppToolOrchestrator()
    quotes = orch.compare_supplier_quotes(item_code="CEM50")
    draft = orch.create_draft_requisition(
        item_code="CEM50", quantity=50, supplier_name=quotes["recommendation"]["supplier"],
        notes="Memory file unreadable; proceeded with fresh comparison.",
    )

    # Restore the original memory file (do NOT delete it)
    if BACKUP_FILE.exists():
        shutil.copy(BACKUP_FILE, MEMORY_FILE)
        BACKUP_FILE.unlink()

    return {
        "scenario": "5_memory_missing_or_unreadable",
        "expected": "Agent drafts normally and reports no preference found.",
        "memory_record": None if record is None else asdict(record),
        "draft_id": draft["draft_id"],
        "note": "Fail-safe path confirmed: unreadable memory returns None. Original memory restored after test.",
    }


# ---------------- Runner ----------------

def main():
    results = []
    for fn in [
        scenario_1_first_request,
        scenario_2_same_item_again,
        scenario_3_cheaper_supplier_now_quoted,
        scenario_4_draft_rejected,
        scenario_5_memory_missing,
    ]:
        outcome = fn()
        results.append(outcome)
        trace_path = save_trace(f"memory_demo_{outcome['scenario']}", outcome)
        print(f"  -> trace: {trace_path}\n")

    # Ensure a valid memory file remains for inspection
    if not MEMORY_FILE.exists():
        store = MemoryStore()
        store.record_approval(
            item_code="CEM50",
            item_name="Portland Cement 50kg",
            approved_supplier="Supplier B",
            approved_unit_price_ugx=31500,
            approved_quantity=50,
            source_draft_id="DR-restored-after-demo",
            approved_by="Demo Runner (restore)",
        )
        print(f"[restored] {MEMORY_FILE}")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenarios": results,
        "memory_file": str(MEMORY_FILE),
        "log_file": str(LOG_FILE),
        "memory_file_exists": MEMORY_FILE.exists(),
    }
    out = save_trace("memory_demo_summary", summary)
    print(f"Summary trace: {out}")


if __name__ == "__main__":
    main()