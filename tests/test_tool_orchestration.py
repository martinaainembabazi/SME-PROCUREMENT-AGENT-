import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from orchestration import AppToolOrchestrator


class ToolOrchestrationTests(unittest.TestCase):
    def test_get_inventory_snapshot_returns_stock_status(self):
        orchestrator = AppToolOrchestrator()
        result = orchestrator.get_inventory_snapshot(item_code="CEM50")

        self.assertIn("items", result)
        self.assertGreater(len(result["items"]), 0)
        self.assertIn("status", result["items"][0])

    def test_create_draft_requisition_writes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = AppToolOrchestrator(base_dir=Path(tmpdir))
            result = orchestrator.create_draft_requisition(
                item_code="CEM50",
                quantity=20,
                supplier_name="Supplier A",
                notes="Draft requisition for approval review."
            )

            self.assertIn("draft_id", result)
            self.assertTrue(Path(result["path"]).exists())
            payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "pending_human_approval")

    def test_get_reorder_candidates_returns_low_stock_items(self):
        orchestrator = AppToolOrchestrator()
        result = orchestrator.get_reorder_candidates()

        self.assertIn("items", result)
        self.assertGreater(len(result["items"]), 0)
        self.assertTrue(any(item["status"] == "reorder_required" for item in result["items"]))

    def test_compare_supplier_quotes_returns_ranked_quotes(self):
        orchestrator = AppToolOrchestrator()
        result = orchestrator.compare_supplier_quotes(item_code="CEM50")

        self.assertIn("item_code", result)
        self.assertIn("quotes", result)
        self.assertGreater(len(result["quotes"]), 0)
        self.assertIn("supplier", result["quotes"][0])


if __name__ == "__main__":
    unittest.main()
