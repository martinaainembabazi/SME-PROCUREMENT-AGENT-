"""Validated create/update/delete for the inventory register and supplier quotations.

These are human-facing operations used by the web app. The agent never calls
them: its tools in orchestration.py stay read-only (plus draft creation), and
read the same files this module writes.

Files:
    knowledge/inventory/current_stock.csv
    knowledge/quotations/quotation_comparison_001.json
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from security import MAX_DRAFT_QUANTITY

ROOT = Path(__file__).resolve().parent.parent

INVENTORY_FIELDS = [
    "item_code",
    "item_name",
    "unit",
    "current_qty",
    "reorder_threshold",
    "last_restock_date",
    "avg_weekly_sales",
]
ITEM_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
MAX_PRICE_UGX = 1_000_000_000


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(tmp, path)


def normalize_item_code(value: Any) -> str:
    code = str(value or "").strip().upper()
    if not ITEM_CODE_PATTERN.match(code):
        raise ValueError(
            "Item code must be 1-32 characters: letters, digits, '-' or '_'."
        )
    return code


def normalize_supplier(value: Any) -> str:
    """'Supplier B', 'supplier b' and 'B' all refer to supplier 'B'."""
    text = " ".join(str(value or "").split())
    if text.lower().startswith("supplier "):
        text = text[len("supplier "):]
    if not text or len(text) > 120:
        raise ValueError("Supplier name must be 1-120 characters.")
    return text.upper() if len(text) <= 3 else text


def _text(value: Any, field: str, maximum: int, required: bool = True) -> str:
    text = " ".join(str(value or "").split())
    if required and not text:
        raise ValueError(f"{field} is required.")
    if len(text) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters.")
    return text


def _int(value: Any, field: str, minimum: int = 0, maximum: int = MAX_DRAFT_QUANTITY) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a whole number.")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a whole number.") from None
    if isinstance(value, float) and value != number:
        raise ValueError(f"{field} must be a whole number.")
    if not minimum <= number <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum:,}.")
    return number


class InventoryStore:
    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else ROOT
        self.path = self.base_dir / "knowledge" / "inventory" / "current_stock.csv"

    def list_items(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        items = []
        for row in rows:
            item = {field: (row.get(field) or "").strip() for field in INVENTORY_FIELDS}
            for field in ("current_qty", "reorder_threshold", "avg_weekly_sales"):
                try:
                    item[field] = int(item[field])
                except ValueError:
                    item[field] = 0
            items.append(item)
        return items

    def get_item(self, item_code: str) -> dict[str, Any] | None:
        code = str(item_code or "").strip().upper()
        return next((i for i in self.list_items() if i["item_code"].upper() == code), None)

    def _validate(self, data: dict[str, Any]) -> dict[str, Any]:
        restock = str(data.get("last_restock_date") or "").strip()
        if restock:
            try:
                restock = date.fromisoformat(restock).isoformat()
            except ValueError:
                raise ValueError("Last restock date must be YYYY-MM-DD.") from None
        return {
            "item_code": normalize_item_code(data.get("item_code")),
            "item_name": _text(data.get("item_name"), "Item name", 200),
            "unit": _text(data.get("unit"), "Unit", 40),
            "current_qty": _int(data.get("current_qty"), "Current quantity"),
            "reorder_threshold": _int(data.get("reorder_threshold"), "Reorder threshold"),
            "last_restock_date": restock,
            "avg_weekly_sales": _int(data.get("avg_weekly_sales", 0), "Average weekly sales"),
        }

    def _save(self, items: list[dict[str, Any]]) -> None:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=INVENTORY_FIELDS, lineterminator="\n")
        writer.writeheader()
        for item in items:
            writer.writerow({field: item.get(field, "") for field in INVENTORY_FIELDS})
        _atomic_write(self.path, buffer.getvalue())

    def add_item(self, data: dict[str, Any]) -> dict[str, Any]:
        item = self._validate(data)
        items = self.list_items()
        if any(i["item_code"].upper() == item["item_code"] for i in items):
            raise ValueError(f"Item {item['item_code']} already exists.")
        items.append(item)
        self._save(items)
        return item

    def update_item(self, item_code: str, data: dict[str, Any]) -> dict[str, Any]:
        code = normalize_item_code(item_code)
        item = self._validate({**data, "item_code": code})
        items = self.list_items()
        for index, existing in enumerate(items):
            if existing["item_code"].upper() == code:
                items[index] = item
                self._save(items)
                return item
        raise ValueError(f"Item {code} does not exist.")

    def delete_item(self, item_code: str) -> None:
        code = normalize_item_code(item_code)
        items = self.list_items()
        remaining = [i for i in items if i["item_code"].upper() != code]
        if len(remaining) == len(items):
            raise ValueError(f"Item {code} does not exist.")
        self._save(remaining)

    def receive_stock(self, item_code: str, quantity: int, received_on: date | None = None) -> dict[str, Any]:
        """Add delivered goods to stock and record the restock date."""
        item = self.get_item(item_code)
        if item is None:
            raise ValueError(f"Item {item_code} is not in the stock register.")
        quantity = _int(quantity, "Received quantity", minimum=1)
        item["current_qty"] += quantity
        item["last_restock_date"] = (received_on or date.today()).isoformat()
        return self.update_item(item["item_code"], item)


class QuoteStore:
    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else ROOT
        self.path = self.base_dir / "knowledge" / "quotations" / "quotation_comparison_001.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"request_id": "QR-001", "comparison": [], "decision_status": "pending_human_review"}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("comparison"), list):
            raise ValueError("Quotation file has an invalid structure.")
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        _atomic_write(self.path, json.dumps(payload, indent=2) + "\n")

    def _entry(self, payload: dict[str, Any], item_code: str, create: bool = False) -> dict[str, Any] | None:
        for entry in payload["comparison"]:
            if str(entry.get("item_code", "")).upper() == item_code:
                return entry
        if not create:
            return None
        entry = {"item_code": item_code, "quotes": [], "notes": ""}
        payload["comparison"].append(entry)
        return entry

    def list_quotes(self, item_code: str | None = None) -> list[dict[str, Any]]:
        """Flat list of quotes: one row per item/supplier."""
        rows = []
        for entry in self._load()["comparison"]:
            code = str(entry.get("item_code", "")).upper()
            if item_code and code != str(item_code).strip().upper():
                continue
            for quote in entry.get("quotes", []):
                rows.append({"item_code": code, **quote})
        return rows

    def get_quote(self, item_code: str, supplier: str) -> dict[str, Any] | None:
        wanted = normalize_supplier(supplier)
        for quote in self.list_quotes(item_code):
            if normalize_supplier(quote.get("supplier")) == wanted:
                return quote
        return None

    def get_notes(self, item_code: str) -> str:
        entry = self._entry(self._load(), normalize_item_code(item_code))
        return str(entry.get("notes", "")) if entry else ""

    def set_notes(self, item_code: str, notes: str) -> None:
        payload = self._load()
        entry = self._entry(payload, normalize_item_code(item_code), create=True)
        entry["notes"] = _text(notes, "Notes", 2_000, required=False)
        self._save(payload)

    def upsert_quote(self, item_code: str, data: dict[str, Any]) -> dict[str, Any]:
        """Add a supplier quote for an item, or replace that supplier's existing quote."""
        code = normalize_item_code(item_code)
        price = data.get("price_ugx")
        if isinstance(price, bool):
            raise ValueError("Price must be a number.")
        try:
            price = float(price)
        except (TypeError, ValueError):
            raise ValueError("Price must be a number.") from None
        if not 0 < price <= MAX_PRICE_UGX:
            raise ValueError(f"Price must be between 1 and {MAX_PRICE_UGX:,} UGX.")
        quote = {
            "supplier": normalize_supplier(data.get("supplier")),
            "price_ugx": int(price) if price.is_integer() else price,
            "moq": _int(data.get("moq"), "MOQ", minimum=1),
            "lead_time_days": _int(data.get("lead_time_days"), "Lead time (days)", maximum=365),
            "payment_terms": _text(data.get("payment_terms"), "Payment terms", 120),
        }
        payload = self._load()
        entry = self._entry(payload, code, create=True)
        quotes = [q for q in entry.get("quotes", []) if normalize_supplier(q.get("supplier")) != quote["supplier"]]
        quotes.append(quote)
        entry["quotes"] = sorted(quotes, key=lambda q: str(q["supplier"]))
        self._save(payload)
        return {"item_code": code, **quote}

    def delete_quote(self, item_code: str, supplier: str) -> None:
        code = normalize_item_code(item_code)
        wanted = normalize_supplier(supplier)
        payload = self._load()
        entry = self._entry(payload, code)
        if entry is None:
            raise ValueError(f"No quotes recorded for {code}.")
        before = len(entry.get("quotes", []))
        entry["quotes"] = [q for q in entry.get("quotes", []) if normalize_supplier(q.get("supplier")) != wanted]
        if len(entry["quotes"]) == before:
            raise ValueError(f"No quote from supplier {wanted} for {code}.")
        self._save(payload)
