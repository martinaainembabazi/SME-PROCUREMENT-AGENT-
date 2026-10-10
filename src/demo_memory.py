"""Week 6 memory demonstration.

Runs every scenario in the Memory Design and Data Handling Note against a THROW-AWAY COPY of
knowledge/, so your real quotations, drafts and memory file are never touched. Evidence is
saved to evidence/week6/.

Usage (from the folder that contains orchestration.py):
    python demo_memory.py
    python demo_memory.py --item SKU-001
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orchestration import ROOT, AppToolOrchestrator
from memory_store import ApprovedSupplierMemory, prepare_draft_context

APPROVER = "Store Manager (demo)"

lines: list[str] = []
results: list[tuple[str, bool]] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def show(label: str, obj) -> None:
    say(f"{label}:")
    say(json.dumps(obj, indent=2, default=str))


def check(label: str, condition: bool) -> None:
    results.append((label, bool(condition)))
    say(f"  [{'PASS' if condition else 'FAIL'}] {label}")


def banner(title: str) -> None:
    say()
    say("=" * 78)
    say(title)
    say("=" * 78)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def usable_items(orch: AppToolOrchestrator, quote_path: Path) -> list[str]:
    inventory = {r.get("item_code", "").strip().upper() for r in orch._read_inventory_rows()}
    payload = json.loads(quote_path.read_text(encoding="utf-8"))
    return [
        e["item_code"]
        for e in payload.get("comparison", [])
        if e.get("item_code", "").upper() in inventory and len(e.get("quotes", [])) >= 2
    ]


def read_log(memory: ApprovedSupplierMemory) -> list[dict]:
    if not memory.log_path.exists():
        return []
    return [json.loads(l) for l in memory.log_path.read_text(encoding="utf-8").splitlines() if l.strip()]


def run(item_arg: str | None, sandbox: Path, out_dir: Path) -> None:
    shutil.copytree(ROOT / "knowledge", sandbox / "knowledge")
    orch = AppToolOrchestrator(base_dir=sandbox)
    memory = ApprovedSupplierMemory(base_dir=sandbox, stale_after_days=90)
    quote_path = sandbox / "knowledge" / "quotations" / "quotation_comparison_001.json"

    candidates = usable_items(orch, quote_path)
    if not candidates:
        sys.exit("No item with 2+ quotes found in BOTH inventory and quotations. Check the data files.")
    if item_arg:
        if item_arg.upper() not in [c.upper() for c in candidates]:
            sys.exit(f"{item_arg} is not usable. Usable items: {candidates}")
        item = item_arg.upper()
    else:
        item = candidates[0].upper()

    say(f"Memory demonstration  |  {datetime.now(timezone.utc).isoformat()}")
    say(f"Item under test: {item}   (sandbox: {sandbox})")
    say(f"Memory file: {memory.path.name}   stale after: {memory.stale_after.days} days")

    # ---------------------------------------------------------------- Run 1
    banner("RUN 1: first request, no record exists, human approves")
    ctx = prepare_draft_context(orch, memory, item)
    show("Drafting context", ctx)
    check("no memory file exists yet", not memory.path.exists())
    check("memory status is no_record", ctx["memory_status"] == "no_record")
    check("no supplier pre-filled", ctx["prefill_supplier"] is None)
    check("agent reports no preference found", "no_preference_found" in ctx["flags"])
    check("live quotes available (2+)", len(ctx["live_quotes"]) >= 2)

    chosen = ctx["live_quotes"][0]
    draft = orch.call_tool("create_draft_requisition", {
        "item_code": item, "quantity": 10, "supplier_name": chosen["supplier"],
        "notes": "Memory demo run 1", "draft_id": "DR-DEMO-RUN1",
    })
    show("Draft created", draft["record"])
    check("draft is pending_human_approval", draft["status"] == "pending_human_approval")
    check("creating a draft does not write memory", not memory.path.exists())

    approval = memory.record_approval("DR-DEMO-RUN1", APPROVER, chosen.get("price_ugx"))
    show("Memory record written after approval", approval["record"])
    check("memory file now exists", memory.path.exists())
    check("record holds the approved supplier", approval["record"]["approved_supplier"] == chosen["supplier"])
    check("record names approver and source draft",
          approval["record"]["approved_by"] == APPROVER and approval["record"]["source_draft_id"] == "DR-DEMO-RUN1")
    snap_run1 = memory.path.read_text(encoding="utf-8")
    (out_dir / "memory_after_run1_approval.json").write_text(snap_run1, encoding="utf-8")

    try:
        memory.record_approval("DR-DEMO-RUN1", "")
        check("approval without a named human is refused", False)
    except ValueError:
        check("approval without a named human is refused", True)

    # ---------------------------------------------------------------- Run 2
    banner("RUN 2: same item again, supplier pre-filled with source label")
    ctx = prepare_draft_context(orch, memory, item)
    show("Drafting context", ctx)
    check("memory status is found", ctx["memory_status"] == "found")
    check("approved supplier pre-filled", ctx["prefill_supplier"] and ctx["prefill_supplier"]["supplier"] == chosen["supplier"])
    check("pre-fill carries source label (date + draft ID)",
          ctx["prefill_supplier"] and "DR-DEMO-RUN1" in ctx["prefill_supplier"]["label"])
    check("no warning flags while the remembered supplier is still best", ctx["flags"] == [])
    check("human decision still required", ctx["requires_human_decision"] is True)

    # ---------------------------------------------------------------- Run 3
    banner("RUN 3: a cheaper supplier appears, memory must not override")
    payload = json.loads(quote_path.read_text(encoding="utf-8"))
    entry = next(e for e in payload["comparison"] if e["item_code"].upper() == item)
    remembered_quote = next(q for q in entry["quotes"] if q["supplier"] == chosen["supplier"])
    other = next(q for q in entry["quotes"] if q["supplier"] != chosen["supplier"])
    other["price_ugx"] = max(1, int(remembered_quote["price_ugx"] * 0.9))
    quote_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    say(f"(sandbox quotes edited: {other['supplier']} now {other['price_ugx']} UGX, "
        f"below remembered {remembered_quote['supplier']} at {remembered_quote['price_ugx']} UGX)")

    before = sha(memory.path)
    ctx = prepare_draft_context(orch, memory, item)
    show("Drafting context", ctx)
    check("remembered supplier still shown, as a suggestion only", ctx["prefill_supplier"] is not None)
    check("cheaper quote is flagged", "cheaper_or_faster_quote_available" in ctx["flags"])
    check("cheapest live quote is NOT the remembered supplier", ctx["live_quotes"][0]["supplier"] != chosen["supplier"])
    check("human decision still required", ctx["requires_human_decision"] is True)
    check("reading memory did not change the file", sha(memory.path) == before)

    # ---------------------------------------------------------------- Run 4
    banner("RUN 4: draft rejected, nothing written to memory")
    hash_before = sha(memory.path)
    say(f"memory file sha256 BEFORE: {hash_before}")
    orch.call_tool("create_draft_requisition", {
        "item_code": item, "quantity": 25, "supplier_name": other["supplier"],
        "notes": "Memory demo run 4", "draft_id": "DR-DEMO-RUN4",
    })
    rejection = memory.record_rejection("DR-DEMO-RUN4", APPROVER, "Quantity needs review")
    show("Rejection result", rejection)
    hash_after = sha(memory.path)
    say(f"memory file sha256 AFTER:  {hash_after}")
    draft4 = json.loads((orch.drafts_dir / "DR-DEMO-RUN4.json").read_text(encoding="utf-8"))
    check("memory file byte-for-byte unchanged", hash_before == hash_after)
    check("draft marked rejected", draft4["status"] == "rejected")
    check("skipped write is logged", any(e["event"] == "memory_write_skipped" and e["record_id"] == "DR-DEMO-RUN4" for e in read_log(memory)))
    (out_dir / "memory_after_run4_rejection.json").write_text(memory.path.read_text(encoding="utf-8"), encoding="utf-8")

    # ---------------------------------------------------------------- Run 5
    banner("RUN 5: memory file unreadable, agent drafts normally")
    memory.path.write_text("{this is not valid json", encoding="utf-8")
    ctx = prepare_draft_context(orch, memory, item)
    show("Drafting context", ctx)
    check("no crash, status memory_unavailable", ctx["memory_status"] == "memory_unavailable")
    check("no supplier invented or pre-filled", ctx["prefill_supplier"] is None)
    check("agent reports no preference applied", "memory_unavailable_no_preference_applied" in ctx["flags"])
    check("live quotes still returned", len(ctx["live_quotes"]) >= 2)
    memory.path.write_text(snap_run1, encoding="utf-8")  # restore

    # ------------------------------------------------- Bonus checks (retention)
    banner("BONUS A: stale record is shown with a warning, never pre-filled")
    records = json.loads(memory.path.read_text(encoding="utf-8"))
    records[item]["approved_at"] = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    memory.path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    ctx = prepare_draft_context(orch, memory, item)
    show("Drafting context", ctx)
    check("status is stale", ctx["memory_status"] == "stale")
    check("stale record is NOT pre-filled", ctx["prefill_supplier"] is None)
    check("stale warning flagged", "memory_record_stale_not_prefilled" in ctx["flags"])
    memory.path.write_text(snap_run1, encoding="utf-8")  # restore

    banner("BONUS B: authorised human deletes a record")
    try:
        memory.delete(item, "")
        check("deletion without a named human is refused", False)
    except ValueError:
        check("deletion without a named human is refused", True)
    deletion = memory.delete(item, APPROVER)
    ctx = prepare_draft_context(orch, memory, item)
    check("record deleted", deletion["deleted"] is True)
    check("lookup now reports no_record", ctx["memory_status"] == "no_record")

    # ------------------------------------------------------------- Summary
    banner("LOG EXCERPT (memory_log.jsonl)")
    for event in read_log(memory):
        say(json.dumps(event))

    passed = sum(1 for _, ok in results if ok)
    banner(f"SUMMARY: {passed}/{len(results)} checks passed")
    for label, ok in results:
        if not ok:
            say(f"  FAILED: {label}")

    shutil.copy(memory.log_path, out_dir / "memory_log.jsonl")
    shutil.copytree(orch.drafts_dir, out_dir / "drafts", dirs_exist_ok=True)
    (out_dir / "demo_transcript.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nEvidence saved to: {out_dir}")
    if passed != len(results):
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Week 6 memory demonstration")
    parser.add_argument("--item", default=None, help="item_code to test (default: first usable item)")
    parser.add_argument("--keep-sandbox", action="store_true", help="do not delete the temp sandbox afterwards")
    args = parser.parse_args()

    out_dir = ROOT / "evidence" / "week6"
    out_dir.mkdir(parents=True, exist_ok=True)
    sandbox = Path(tempfile.mkdtemp(prefix="memory_demo_"))
    try:
        run(args.item, sandbox, out_dir)
    finally:
        if not args.keep_sandbox:
            shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    main()
