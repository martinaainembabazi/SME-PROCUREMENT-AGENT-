"""Application-level orchestration and tool calls for the SME Procurement agent."""

from __future__ import annotations

import csv
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from guardrail_service import (
    GuardrailService,
    READ_ONLY_TOOLS,
    TOOL_ROLES,
)
from security import MAX_DRAFT_QUANTITY, validate_text


ROOT = Path(__file__).resolve().parent.parent
def _validate_single_line(value: Any, field: str, maximum: int) -> str:
    return GuardrailService.validate_single_line(value, field, maximum)


class AppToolOrchestrator:
    """Expose safe, structured actions for the application layer.

    Two low-risk tools are included:
    - get_inventory_snapshot: read current application inventory data
    - create_draft_requisition: create a draft requisition record for human review
    """

    def __init__(self, base_dir: str | Path | None = None):
        self.guardrails = GuardrailService()
        self.base_dir = Path(base_dir) if base_dir is not None else ROOT
        self.inventory_path = self.base_dir / "knowledge" / "inventory" / "current_stock.csv"
        self.drafts_dir = self.base_dir / "evidence" / "drafts"
        self.drafts_dir.mkdir(parents=True, exist_ok=True)

    def list_tools(self, principal: str = "agent") -> list[dict[str, Any]]:
        allowed_tools = self.guardrails.allowed_tools(principal)
        definitions = [
            {
                "name": "get_inventory_snapshot",
                "description": "Retrieve the current stock snapshot from the application data store.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_code": {
                            "type": ["string", "null"],
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
                            "type": ["string", "null"],
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
        return [
            tool for tool in definitions
            if tool["name"] in allowed_tools
        ]

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        principal: str = "agent",
    ):
        """Authorize and validate a tool call before dispatching it.

        ``principal`` must come from the trusted application boundary, never from
        model output or user-controlled tool arguments.
        """
        try:
            self.guardrails.authorize_tool(tool_name, principal)
        except ValueError as exc:
            raise ValueError(
                f"Unknown tool '{tool_name}'. Available tools: {self.available_tools()}"
            ) from exc
        if arguments is None:
            args: dict[str, Any] = {}
        elif isinstance(arguments, dict):
            args = dict(arguments)
        else:
            raise ValueError("Tool arguments must be an object.")

        self.guardrails.validate_tool_arguments(tool_name, args)

        if tool_name == "get_inventory_snapshot":
            result = self.get_inventory_snapshot(**args)
        elif tool_name == "create_draft_requisition":
            result = self.create_draft_requisition(**args)
        elif tool_name == "get_reorder_candidates":
            result = self.get_reorder_candidates(**args)
        else:
            result = self.compare_supplier_quotes(**args)
        self.guardrails.validate_tool_result(tool_name, result)
        return result

    def available_tools(self) -> list[str]:
        return [tool["name"] for tool in self.list_tools()]

    def _read_inventory_rows(self) -> list[dict[str, str]]:
        if not self.inventory_path.exists():
            return []
        if self.inventory_path.stat().st_size > 2_000_000:
            raise ValueError("Inventory data file exceeds the 2 MB input limit.")

        with self.inventory_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) > 5_000:
            raise ValueError("Inventory data file contains too many rows.")

        return rows

    def get_inventory_snapshot(self, item_code: str | None = None) -> dict[str, Any]:
        """Return a safe read of the current inventory snapshot."""
        if item_code is not None:
            item_code = _validate_single_line(item_code, "item_code", maximum=64)
        rows = self._read_inventory_rows()
        if item_code:
            needle = item_code.strip().upper()
            filtered = [
                row
                for row in rows
                if row.get("item_code", "").upper() == needle
                or needle in row.get("item_name", "").upper()
            ]
        else:
            filtered = rows

        items = []
        for row in filtered:
            try:
                current_qty = int(row["current_qty"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(
                    f"Invalid current_qty for item '{row.get('item_code', 'unknown')}'."
                )

            try:
                reorder_threshold = int(row["reorder_threshold"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(
                    f"Invalid reorder_threshold for item '{row.get('item_code', 'unknown')}'."
                )
            if current_qty < 0 or reorder_threshold < 0:
                raise ValueError(
                    f"Inventory quantities cannot be negative for item '{row.get('item_code', 'unknown')}'."
                )
            item_code_value = validate_text(
                row.get("item_code", ""), "inventory item_code", maximum=64
            )
            item_name = validate_text(
                row.get("item_name", ""), "inventory item_name", maximum=200
            )

            status = "reorder_required" if current_qty < reorder_threshold else "healthy"
            items.append(
                {
                    "item_code": item_code_value,
                    "item_name": item_name,
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
            "data_available": self.inventory_path.exists(),
            "inventory_item_count": len(rows),
            "matched_item_count": len(items),
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
        self.guardrails.validate_tool_arguments(
            "create_draft_requisition",
            {
                "item_code": item_code,
                "quantity": quantity,
                "supplier_name": supplier_name,
                "notes": notes,
                **({"draft_id": draft_id} if draft_id is not None else {}),
            },
        )
        item_code = item_code.strip()
        supplier_name = supplier_name.strip()
        notes = notes.strip()
        quantity_value = quantity
        if draft_id is not None:
            draft_id = draft_id.strip()

        snapshot = self.get_inventory_snapshot(item_code=item_code)
        item = next(
            (
                row for row in snapshot["items"]
                if row["item_code"].strip().upper() == item_code.upper()
            ),
            {"item_name": item_code},
        )

        generated_id = draft_id or (
            f"DR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )
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
            "data_available": snapshot["data_available"],
            "inventory_item_count": snapshot["inventory_item_count"],
            "matched_item_count": snapshot["matched_item_count"],
            "items": items,
        }

    def compare_supplier_quotes(self, item_code: str) -> dict[str, Any]:
        """Return supplier quotes for an item sorted by price, with a simple recommendation."""
        if not item_code or not str(item_code).strip():
            raise ValueError("item_code is required.")
        item_code = _validate_single_line(item_code, "item_code", maximum=64)

        quote_path = self.base_dir / "knowledge" / "quotations" / "quotation_comparison_001.json"
        if not quote_path.exists():
            raise FileNotFoundError(f"Quote file not found: {quote_path}")
        if quote_path.stat().st_size > 2_000_000:
            raise ValueError("Supplier quote file exceeds the 2 MB input limit.")

        payload = json.loads(quote_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("comparison"), list):
            raise ValueError("Supplier quote file has an invalid structure.")
        comparison = payload.get("comparison", [])
        if len(comparison) > 5_000:
            raise ValueError("Supplier quote file contains too many item records.")
        if any(not isinstance(entry, dict) for entry in comparison):
            raise ValueError("Supplier quote file contains an invalid item record.")
        item_quotes = next((entry for entry in comparison if entry.get("item_code") == item_code.upper()), None)

        if item_quotes is None:
            return {
                "item_code": item_code.upper(),
                "quotes": [],
                "recommendation": "No quote data available for this item.",
            }

        quotes = item_quotes.get("quotes", [])
        if not isinstance(quotes, list) or len(quotes) > 5_000:
            raise ValueError(f"Supplier quotes for '{item_code}' have an invalid structure.")
        for quote in quotes:
            if not isinstance(quote, dict):
                raise ValueError(f"Supplier quote for '{item_code}' is invalid.")
            _validate_single_line(quote.get("supplier"), "quote supplier", 120)
            for field in ("price_ugx", "lead_time_days"):
                value = quote.get(field)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or value < 0
                    or value > 1_000_000_000_000_000
                    or (isinstance(value, float) and not math.isfinite(value))
                ):
                    raise ValueError(f"Supplier quote has an invalid {field}.")
            if "moq" in quote and (
                isinstance(quote["moq"], bool)
                or not isinstance(quote["moq"], int)
                or quote["moq"] <= 0
                or quote["moq"] > MAX_DRAFT_QUANTITY
            ):
                raise ValueError("Supplier quote has an invalid moq.")
            if "payment_terms" in quote:
                validate_text(
                    quote["payment_terms"], "payment_terms", maximum=120
                )
        ranked = sorted(quotes, key=lambda q: (q.get("price_ugx", float("inf")), q.get("lead_time_days", float("inf"))))
        if not ranked:
            return {
                "item_code": item_code.upper(),
                "quotes": [],
                "recommendation": "No quote data available for this item.",
                "notes": validate_text(
                    item_quotes.get("notes", ""),
                    "quote notes",
                    maximum=2_000,
                    allow_empty=True,
                ),
            }
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
            "notes": validate_text(
                item_quotes.get("notes", ""),
                "quote notes",
                maximum=2_000,
                allow_empty=True,
            ),
        }


if __name__ == "__main__":
    orchestrator = AppToolOrchestrator()
    print(json.dumps(orchestrator.list_tools(), indent=2))
