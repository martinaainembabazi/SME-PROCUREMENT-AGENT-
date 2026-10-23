# SME Reorder Policy (Team-Created, Synthetic)

**Effective:** 2026-09-01
**Owner:** Procurement Manager (simulated)

## 1. Reorder Trigger
An item must be reordered when its `current_qty` falls below its `reorder_threshold` as recorded in the current stock register.

## 2. Priority Rules
- **High criticality** items are reordered first.
- Items with **lead_time_days > 14** must be ordered **before** the threshold is reached if weekly sales exceed 20% of current stock.

## 3. Order Quantity
For standard reorders, order enough to reach `max_stock` where defined, otherwise `2 × reorder_threshold`.

## 4. Supplier Choice
Choose the supplier with the **best combination of price, lead time, and reliability** — not price alone. See `supplier_selection_criteria.md`.

## 5. Approval
Any order above **UGX 2,000,000** requires owner approval before submission.

## 6. Restrictions
- Never order from a supplier without confirmed payment terms on file.
- Do not commit to a supplier without checking MOQ compliance.
- This agent may **prepare** a requisition, but may **not approve or pay**.