"""Tests for the web app's service layer: auth, data management and requisition lifecycle.

Every test runs against a temporary copy of knowledge/, so real data is never changed.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from auth import UserStore, can, can_approve_amount  # noqa: E402
from data_store import InventoryStore, QuoteStore  # noqa: E402
from requisitions import RequisitionService  # noqa: E402


def make_user(role, username=None):
    return {"username": username or role, "full_name": f"Test {role}", "role": role}


class TempProjectTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        for rel in ("knowledge/inventory/current_stock.csv", "knowledge/quotations/quotation_comparison_001.json"):
            target = self.base / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / rel, target)

    def tearDown(self):
        self._tmp.cleanup()


class AuthTests(TempProjectTestCase):
    def test_create_and_authenticate_user(self):
        store = UserStore(self.base)
        store.create_user("owner1", "correct horse", "owner", "Olive Owner")
        self.assertIsNotNone(store.authenticate("OWNER1", "correct horse"))
        self.assertIsNone(store.authenticate("owner1", "wrong password"))
        raw = json.loads((self.base / "data" / "users.json").read_text())
        self.assertNotIn("correct horse", json.dumps(raw))

    def test_rejects_short_password_and_bad_role(self):
        store = UserStore(self.base)
        with self.assertRaises(ValueError):
            store.create_user("user1", "short", "viewer", "Val Viewer")
        with self.assertRaises(ValueError):
            store.create_user("user1", "long enough", "admin", "Val Viewer")

    def test_deactivated_user_cannot_sign_in(self):
        store = UserStore(self.base)
        store.create_user("owner1", "password1", "owner", "Olive Owner")
        store.create_user("viewer1", "password1", "viewer", "Val Viewer")
        store.update_user("viewer1", active=False)
        self.assertIsNone(store.authenticate("viewer1", "password1"))

    def test_repeated_failures_lock_account_until_password_reset(self):
        store = UserStore(self.base)
        store.create_user("owner1", "password1", "owner", "Olive Owner")
        for _ in range(5):
            self.assertIsNone(store.authenticate("owner1", "wrong"))
        self.assertTrue(store.is_username_locked("owner1"))
        self.assertIsNone(store.authenticate("owner1", "password1"))  # correct, but locked
        store.update_user("owner1", password="password2")
        self.assertIsNotNone(store.authenticate("owner1", "password2"))

    def test_success_resets_failure_count(self):
        store = UserStore(self.base)
        store.create_user("owner1", "password1", "owner", "Olive Owner")
        for _ in range(4):
            store.authenticate("owner1", "wrong")
        self.assertIsNotNone(store.authenticate("owner1", "password1"))
        for _ in range(4):
            store.authenticate("owner1", "wrong")
        self.assertFalse(store.is_username_locked("owner1"))

    def test_last_owner_cannot_be_demoted(self):
        store = UserStore(self.base)
        store.create_user("owner1", "password1", "owner", "Olive Owner")
        with self.assertRaisesRegex(ValueError, "Business Owner"):
            store.update_user("owner1", role="manager")

    def test_approval_limits_follow_policy(self):
        self.assertFalse(can(make_user("officer"), "approve"))
        self.assertTrue(can_approve_amount(make_user("manager"), 1_999_999)[0])
        self.assertFalse(can_approve_amount(make_user("manager"), 2_000_000)[0])
        self.assertTrue(can_approve_amount(make_user("owner"), 50_000_000)[0])
        self.assertFalse(can_approve_amount(make_user("owner"), None)[0])


class DataStoreTests(TempProjectTestCase):
    def test_inventory_add_update_delete(self):
        store = InventoryStore(self.base)
        store.add_item({"item_code": "beans1", "item_name": "Beans 1kg", "unit": "bag",
                        "current_qty": 5, "reorder_threshold": 10, "avg_weekly_sales": 3})
        self.assertEqual(store.get_item("BEANS1")["current_qty"], 5)
        with self.assertRaisesRegex(ValueError, "already exists"):
            store.add_item({"item_code": "BEANS1", "item_name": "x", "unit": "bag",
                            "current_qty": 1, "reorder_threshold": 1})
        store.update_item("BEANS1", {"item_name": "Beans 1kg", "unit": "bag",
                                     "current_qty": 20, "reorder_threshold": 10})
        self.assertEqual(store.get_item("BEANS1")["current_qty"], 20)
        store.delete_item("BEANS1")
        self.assertIsNone(store.get_item("BEANS1"))

    def test_inventory_validation(self):
        store = InventoryStore(self.base)
        with self.assertRaises(ValueError):
            store.add_item({"item_code": "bad code!", "item_name": "x", "unit": "bag",
                            "current_qty": 1, "reorder_threshold": 1})
        with self.assertRaises(ValueError):
            store.add_item({"item_code": "NEG1", "item_name": "x", "unit": "bag",
                            "current_qty": -1, "reorder_threshold": 1})

    def test_agent_tools_see_inventory_edits(self):
        from orchestration import AppToolOrchestrator

        InventoryStore(self.base).add_item({"item_code": "SALT1", "item_name": "Salt", "unit": "bag",
                                            "current_qty": 1, "reorder_threshold": 50})
        result = AppToolOrchestrator(self.base).call_tool("get_reorder_candidates", {"item_code": "SALT1"})
        self.assertEqual([i["item_code"] for i in result["items"]], ["SALT1"])

    def test_quote_upsert_replaces_same_supplier_and_feeds_tool(self):
        from orchestration import AppToolOrchestrator

        quotes = QuoteStore(self.base)
        quotes.upsert_quote("SOAP1", {"supplier": "Supplier A", "price_ugx": 60000, "moq": 5,
                                      "lead_time_days": 4, "payment_terms": "Net 30"})
        quotes.upsert_quote("SOAP1", {"supplier": "a", "price_ugx": 58000, "moq": 5,
                                      "lead_time_days": 4, "payment_terms": "Net 30"})
        rows = quotes.list_quotes("SOAP1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price_ugx"], 58000)
        result = AppToolOrchestrator(self.base).call_tool("compare_supplier_quotes", {"item_code": "SOAP1"})
        self.assertEqual(result["recommendation"]["supplier"], "A")
        quotes.delete_quote("SOAP1", "A")
        self.assertEqual(quotes.list_quotes("SOAP1"), [])

    def test_quote_requires_payment_terms(self):
        with self.assertRaisesRegex(ValueError, "Payment terms"):
            QuoteStore(self.base).upsert_quote("RICE5", {"supplier": "D", "price_ugx": 1000, "moq": 1,
                                                         "lead_time_days": 1, "payment_terms": ""})


class RequisitionLifecycleTests(TempProjectTestCase):
    def setUp(self):
        super().setUp()
        self.service = RequisitionService(self.base)

    def test_full_lifecycle_updates_memory_and_stock(self):
        officer, manager = make_user("officer"), make_user("manager")
        # RICE5 from supplier A: 20 x 85,000 = 1,700,000 (below the owner threshold)
        draft = self.service.create_manual(officer, "RICE5", 20, "A", "weekly top-up")
        self.assertEqual(draft["status"], "pending_human_approval")
        self.assertEqual(self.service.evaluate(draft)["total_ugx"], 1_700_000)

        approved = self.service.approve(manager, draft["draft_id"])
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["approved_total_ugx"], 1_700_000)
        self.assertEqual(self.service.memory.lookup("RICE5")["status"], "found")

        before = self.service.inventory.get_item("RICE5")["current_qty"]
        received = self.service.receive(officer, draft["draft_id"], 20)
        self.assertEqual(received["status"], "received")
        self.assertEqual(self.service.inventory.get_item("RICE5")["current_qty"], before + 20)

    def test_manager_cannot_approve_at_or_above_threshold(self):
        draft = self.service.create_manual(make_user("officer"), "RICE5", 40, "B")  # 3,280,000
        with self.assertRaisesRegex(PermissionError, "Business Owner"):
            self.service.approve(make_user("manager"), draft["draft_id"])
        self.assertEqual(self.service.approve(make_user("owner"), draft["draft_id"])["status"], "approved")

    def test_moq_and_missing_quote_block_approval(self):
        below_moq = self.service.create_manual(make_user("officer"), "RICE5", 5, "B")  # MOQ 20
        with self.assertRaisesRegex(ValueError, "MOQ"):
            self.service.approve(make_user("owner"), below_moq["draft_id"])
        no_quote = self.service.create_manual(make_user("officer"), "SOAP1", 10, "A")
        with self.assertRaisesRegex(ValueError, "No quote"):
            self.service.approve(make_user("owner"), no_quote["draft_id"])

    def test_rejection_requires_reason_and_skips_memory(self):
        draft = self.service.create_manual(make_user("officer"), "OIL1L", 10, "A")
        with self.assertRaisesRegex(ValueError, "reason"):
            self.service.reject(make_user("manager"), draft["draft_id"], "  ")
        rejected = self.service.reject(make_user("manager"), draft["draft_id"], "Stock arriving from transfer")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(self.service.memory.lookup("OIL1L")["status"], "no_record")

    def test_roles_are_enforced(self):
        with self.assertRaises(PermissionError):
            self.service.create_manual(make_user("viewer"), "RICE5", 20, "A")
        draft = self.service.create_manual(make_user("officer"), "RICE5", 20, "A")
        with self.assertRaises(PermissionError):
            self.service.approve(make_user("officer"), draft["draft_id"])
        with self.assertRaises(ValueError):
            self.service.receive(make_user("officer"), draft["draft_id"], 20)  # not approved yet

    def test_requisition_ids_cannot_escape_drafts_folder(self):
        with self.assertRaises(ValueError):
            self.service.get("../../data/users")

    def test_export_contains_totals(self):
        draft = self.service.create_manual(make_user("officer"), "RICE5", 20, "A")
        text = self.service.export_csv(draft)
        self.assertIn("1700000", text)
        self.assertIn(draft["draft_id"], text)


if __name__ == "__main__":
    unittest.main()
