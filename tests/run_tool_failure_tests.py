"""
Week 4 — Failure & Authorization Test Runner
SME Procurement-Preparation Agent (CAC Supermarket, Kyanja)

Runs failure and authorization tests against AppToolOrchestrator.
Produces: evidence/week4_tool_failure_results.json
"""
from __future__ import annotations

import json
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Ensure src/ is importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from orchestration import AppToolOrchestrator  # noqa: E402


CASES_PATH = ROOT / "tests" / "tool_failure_tests.json"
OUTPUT_PATH = ROOT / "evidence" / "week4_tool_failure_results.json"


def evaluate(outcome: dict) -> bool:
    """Heuristic pass/fail aligned to expected behaviour."""
    expected = outcome["expected"].lower()
    result = outcome["result"]
    detail = str(outcome.get("detail", "")).lower()

    # --- Special case F13: fallback to full list is acceptable ---
    if outcome["id"] == "F13":
        if result == "success" and isinstance(outcome["detail"], dict):
            items = outcome["detail"].get("items", [])
            fake = [i for i in items if i.get("item_code") == "NOT_A_REAL_ITEM"]
            return len(fake) == 0
        return False

    # Unknown tool
    if "unknown tool" in expected:
        return result == "value_error" and "unknown tool" in detail

    # Required field missing
    if "required" in expected and "raises valueerror" in expected:
        return result == "value_error" and "required" in detail

    # Quantity must be integer
    if "must be an integer" in expected:
        return result == "value_error" and "integer" in detail

    # Quantity > 0
    if "greater than zero" in expected:
        return result == "value_error" and "greater than zero" in detail

    # File not found
    if "filenotfounderror" in expected:
        return result == "file_not_found"

    # Missing inventory → items: []
    if "items: []" in expected:
        if result == "success" and isinstance(outcome["detail"], dict):
            return outcome["detail"].get("items") == []

    # Empty quotes
    if "quotes: []" in expected:
        if result == "success" and isinstance(outcome["detail"], dict):
            return outcome["detail"].get("quotes") == []

    # Status must be pending_human_approval
    if "pending_human_approval" in expected:
        if result == "success" and isinstance(outcome["detail"], dict):
            return outcome["detail"].get("status") == "pending_human_approval"

    return False


def run_case(orchestrator: AppToolOrchestrator, case: dict, base_dir: Path) -> dict:
    outcome = {
        "id": case["id"],
        "category": case["category"],
        "tool": case["tool"],
        "input": case["input"],
        "expected": case["expected"],
    }

    simulate = case.get("_simulate")
    backed_up: list[tuple[Path, Path]] = []

    try:
        if simulate == "inventory_missing":
            inv = base_dir / "knowledge" / "inventory" / "current_stock.csv"
            if inv.exists():
                backup = inv.with_suffix(".csv.bak")
                shutil.move(str(inv), str(backup))
                backed_up.append((inv, backup))

        if simulate == "quotes_missing":
            qf = base_dir / "knowledge" / "quotations" / "quotation_comparison_001.json"
            if qf.exists():
                backup = qf.with_suffix(".json.bak")
                shutil.move(str(qf), str(backup))
                backed_up.append((qf, backup))

        result = orchestrator.call_tool(case["tool"], case["input"])
        outcome["result"] = "success"
        outcome["detail"] = result

    except ValueError as e:
        outcome["result"] = "value_error"
        outcome["detail"] = str(e)
    except FileNotFoundError as e:
        outcome["result"] = "file_not_found"
        outcome["detail"] = str(e)
    except KeyError as e:
        outcome["result"] = "key_error"
        outcome["detail"] = str(e)
    except Exception as e:
        outcome["result"] = "unexpected_error"
        outcome["detail"] = f"{type(e).__name__}: {e}"
        outcome["trace"] = traceback.format_exc()

    finally:
        for original, backup in backed_up:
            if backup.exists():
                shutil.move(str(backup), str(original))

    outcome["passed"] = evaluate(outcome)
    return outcome


def main():
    cases = json.loads(CASES_PATH.read_text())
    orchestrator = AppToolOrchestrator(base_dir=ROOT)

    results = [run_case(orchestrator, c, ROOT) for c in cases]
    passed = sum(1 for r in results if r["passed"])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": "SME Procurement-Preparation Agent (CAC Supermarket, Kyanja)",
        "week": 4,
        "deliverable": "Failure / Authorization Test Evidence",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "cases": results,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{r['id']}] {r['category']:32} {r['result']:20} {status}")
    print(f"\nPassed {passed}/{len(results)}")
    print(f"Report: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()