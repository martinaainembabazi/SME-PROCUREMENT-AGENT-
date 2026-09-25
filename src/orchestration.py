"""Application-level orchestration and tool calls for the SME Procurement agent."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent


class AppToolOrchestrator:
    """Expose safe, structured actions for the application layer.

    Two low-risk tools are included:
    - get_inventory_snapshot: read current application inventory data
    - create_draft_requisition: create a draft requisition record for human review
    """

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else ROOT
        self.inventory_path = self.base_dir / "knowledge" / "inventory" / "current_stock.csv"
        self.drafts_dir = self.base_dir / "evidence" / "drafts"
        self.drafts_dir.mkdir(parents=True, exist_ok=True)

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "get_inventory_snapshot",
                "description": "Retrieve the current stock snapshot from the application data store.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_code": {
                            "type": "string",
                            "description": "Optional item code or item name fragment to filter the inventory snapshot.",
                        }
                    },
                    "required": [],
                },
            },
            {
                "name": "create_draft_requisition",
                "description": "Create a simulated draft requisition record for approval review without placing an order.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_code": {"type": "string"},
                        "quantity": {"type": "integer"},
                        "supplier_name": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["item_code", "quantity", "supplier_name"],
                },
            },
            {
                "name": "get_reorder_candidates",
                "description": "Identify items whose current quantity is below reorder threshold based on the inventory register.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_code": {
                            "type": "string",
                            "description": "Optional item code to filter the reorder candidate list.",
                        }
                    },
                    "required": [],
                },
            },
            {
                "name": "compare_supplier_quotes",
                "description": "Compare supplier quotes for a specific item using price, lead time, MOQ, and payment terms without creating a purchase.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_code": {"type": "string"},
                    },
                    "required": ["item_code"],
                },
            },
        ]

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None):
        """Dispatch a tool by name using an application-layer function call pattern."""
        args = arguments or {}
        tool_name = tool_name.strip()

        if tool_name == "get_inventory_snapshot":
            return self.get_inventory_snapshot(**args)

        if tool_name == "create_draft_requisition":
            return self.create_draft_requisition(**args)

        if tool_name == "get_reorder_candidates":
            return self.get_reorder_candidates(**args)

        if tool_name == "compare_supplier_quotes":
            return self.compare_supplier_quotes(**args)

        raise ValueError(f"Unknown tool '{tool_name}'. Available tools: {self.available_tools()}")

    def available_tools(self) -> list[str]:
        return [tool["name"] for tool in self.list_tools()]

    def _read_inventory_rows(self) -> list[dict[str, str]]:
        if not self.inventory_path.exists():
            return []

        with self.inventory_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        return rows

    def get_inventory_snapshot(self, item_code: str | None = None) -> dict[str, Any]:
        """Return a safe read of the current inventory snapshot."""
        rows = self._read_inventory_rows()
        if item_code:
            needle = item_code.strip().upper()
            filtered = [
                row
                for row in rows
                if row.get("item_code", "").upper() == needle
                or needle in row.get("item_name", "").upper()
            ]
            if not filtered:
                filtered = rows
        else:
            filtered = rows

        items = []
        for row in filtered:
            try:
                current_qty = int(row.get("current_qty", 0) or 0)
            except (TypeError, ValueError):
                current_qty = 0

            try:
                reorder_threshold = int(row.get("reorder_threshold", 0) or 0)
            except (TypeError, ValueError):
                reorder_threshold = 0

            status = "reorder_required" if current_qty < reorder_threshold else "healthy"
            items.append(
                {
                    "item_code": row.get("item_code", ""),
                    "item_name": row.get("item_name", ""),
                    "unit": row.get("unit", ""),
                    "current_qty": current_qty,
                    "reorder_threshold": reorder_threshold,
                    "avg_weekly_sales": row.get("avg_weekly_sales", ""),
                    "last_restock_date": row.get("last_restock_date", ""),
                    "status": status,
                }
            )

        return {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "item_code_filter": item_code,
            "source": str(self.inventory_path),
            "items": items,
        }

    def create_draft_requisition(
        self,
        item_code: str,
        quantity: int,
        supplier_name: str,
        notes: str = "",
        draft_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a low-risk draft purchase requisition record for human approval."""
        if not item_code or not str(item_code).strip():
            raise ValueError("item_code is required.")

        try:
            quantity_value = int(quantity)
        except (TypeError, ValueError) as exc:
            raise ValueError("quantity must be an integer.") from exc

        if quantity_value <= 0:
            raise ValueError("quantity must be greater than zero.")

        if not supplier_name or not str(supplier_name).strip():
            raise ValueError("supplier_name is required.")

        snapshot = self.get_inventory_snapshot(item_code=item_code)
        item = snapshot["items"][0] if snapshot["items"] else {"item_name": item_code}

        generated_id = draft_id or f"DR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        payload = {
            "draft_id": generated_id,
            "item_code": item_code,
            "item_name": item.get("item_name", item_code),
            "quantity": quantity_value,
            "supplier_name": supplier_name,
            "notes": notes,
            "status": "pending_human_approval",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "policy": "No purchase is finalized without human approval.",
        }

        path = self.drafts_dir / f"{generated_id}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        return {
            "draft_id": generated_id,
            "path": str(path),
            "status": "pending_human_approval",
            "record": payload,
        }

    def get_reorder_candidates(self, item_code: str | None = None) -> dict[str, Any]:
        """Return items that are below their reorder threshold."""
        snapshot = self.get_inventory_snapshot(item_code=item_code)
        items = [
            item for item in snapshot["items"] if item["status"] == "reorder_required"
        ]
        return {
            "retrieved_at": snapshot["retrieved_at"],
            "item_code_filter": item_code,
            "items": items,
        }

    def compare_supplier_quotes(self, item_code: str) -> dict[str, Any]:
        """Return supplier quotes for an item sorted by price, with a simple recommendation."""
        if not item_code or not str(item_code).strip():
            raise ValueError("item_code is required.")

        quote_path = self.base_dir / "knowledge" / "quotations" / "quotation_comparison_001.json"
        if not quote_path.exists():
            raise FileNotFoundError(f"Quote file not found: {quote_path}")

        payload = json.loads(quote_path.read_text(encoding="utf-8"))
        comparison = payload.get("comparison", [])
        item_quotes = next((entry for entry in comparison if entry.get("item_code") == item_code.upper()), None)

        if item_quotes is None:
            return {
                "item_code": item_code.upper(),
                "quotes": [],
                "recommendation": "No quote data available for this item.",
            }

        quotes = item_quotes.get("quotes", [])
        ranked = sorted(quotes, key=lambda q: (q.get("price_ugx", float("inf")), q.get("lead_time_days", float("inf"))))
        recommendation = ranked[0]

        return {
            "item_code": item_code.upper(),
            "quotes": ranked,
            "recommendation": {
                "supplier": recommendation.get("supplier"),
                "price_ugx": recommendation.get("price_ugx"),
                "lead_time_days": recommendation.get("lead_time_days"),
                "payment_terms": recommendation.get("payment_terms"),
            },
            "notes": item_quotes.get("notes", ""),
        }


if __name__ == "__main__":
    orchestrator = AppToolOrchestrator()
    print(json.dumps(orchestrator.list_tools(), indent=2))
