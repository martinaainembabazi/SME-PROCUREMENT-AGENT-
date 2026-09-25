# Week 4 — Failure & Authorization Test Evidence

**Project:** SME Procurement-Preparation Agent (CAC Supermarket, Kyanja)
**Team:** Group D
**Week:** 4
**Author:** Joel T., Application/Integration Lead
**Date:** 2026-09-25

---

## 1. Purpose

This document provides evidence that the SME Procurement-Preparation Agent
fails safely, refuses unauthorized actions, and correctly handles missing
data sources. It verifies compliance with the Week 1 AI Boundary Matrix
and the Week 4 Tool Catalogue.

## 2. Scope

The suite exercises the four tools exposed by `AppToolOrchestrator`
in `src/orchestration.py`:

| # | Tool | Authorization |
|---|---|---|
| 1 | `get_inventory_snapshot` | Autonomous / read-only |
| 2 | `get_reorder_candidates` | Autonomous / read-only |
| 3 | `compare_supplier_quotes` | Autonomous / read-only |
| 4 | `create_draft_requisition` | Gated / human review required |

Per the AI Boundary Matrix, the following are **prohibited** to the AI:
- Order authorization
- Payment execution
- Any requisition status other than `pending_human_approval`

## 3. Test Categories

| Category | # Cases |
|---|---|
| Missing required parameter | 3 |
| Invalid data type | 1 |
| Invalid value | 1 |
| Unauthorized payload injection | 1 |
| Unauthorized action attempt | 3 |
| Data store outage | 3 |
| Unknown resource fallback | 1 |
| Unknown resource | 1 |
| Unknown tool | 1 |
| Success baseline | 1 |
| High-impact boundary | 1 |
| Injection in notes | 1 |
| **Total** | **18** |

## 4. Results

Full results: `evidence/week4_tool_failure_results.json`.

### Summary

- Total cases: **18**
- Passed: **18**
- Failed: **0**

### Key Findings

**4.1 Authorization boundaries are enforced.**
- Attempts to inject `status: approved` via notes (F06, F18) are ignored;
  draft status is hardcoded to `pending_human_approval`.
- Non-existent tools (`approve_purchase_order`, `execute_payment`,
  `finalize_requisition`, `delete_all_data`) are refused with
  `ValueError: Unknown tool` (F07, F08, F09, F15).
- Bulk orders (F17) are drafted but never submitted — the AI Boundary
  Matrix rule "Draft Requisition Creation requires human review" holds.

**4.2 Failure behaviour matches the Tool Catalogue's intent.**
- Missing required fields raise `ValueError` (F01–F03).
- Invalid types and values are rejected (F04, F05).
- Missing data files produce empty results, not fabricated data (F10, F11).

**4.3 Empty sets and unknown resources are handled gracefully.**
- Unknown item codes return an empty `quotes` list with a clear
  recommendation (F14).
- Unknown item-code filters on inventory fall back to the full list —
  verified that no fabricated candidate named for the requested item is
  returned (F13).
- Missing inventory file returns `items: []` (F10, F11).

**4.4 AI Boundary Matrix compliance.**

| Boundary Rule | Tests | Status |
|---|---|---|
| Read-only inventory monitoring | F10, F11, F13 | ✅ |
| Read-only quote parsing | F12, F14 | ✅ |
| Draft requisition requires human approval | F06, F16, F17, F18 | ✅ |
| Order authorization prohibited | F07, F09 | ✅ |
| Payment execution prohibited | F08, F15 | ✅ |

## 5. Identified Drift Between Catalogue and Implementation

During test design, the following discrepancies were identified between the
Week 4 Tool Catalogue and the `AppToolOrchestrator` implementation:

| Item | Tool Catalogue | Implementation | Action |
|---|---|---|---|
| Parameter name | `item_name` | `item_code` | Update Catalogue in Week 5 |
| `create_draft_requisition` items | Array of items | Single item per call | Update Catalogue |
| Error style | Returns `{error: ...}` dict | Raises `ValueError` | Update Catalogue |
| `service_unavailable` | Explicit error code | Not implemented | Add for Week 7 hardening |
| `category` filter | Supported | Not implemented | Consider for Week 5 |
| Unknown filter fallback | Not specified | Falls back to full list | Acceptable; documented; no fabrication |

**Recommendation:** Align the Tool Catalogue with the code before Week 5,
and add explicit `service_unavailable` handling as part of Week 7 hardening.

## 6. Evidence Files

- Test cases: `tests/tool_failure_tests.json`
- Runner: `tests/run_tool_failure_tests.py`
- Raw results: `evidence/week4_tool_failure_results.json`
- Console screenshot: `evidence/week4_console_output.png`

## 7. Known Limitations

- `service_unavailable` is simulated by file removal, not by network failure.
- Concurrency and rate-limit behaviour are not tested this week.
- Tests exercise tools directly; end-to-end agent-loop tests are scheduled
  for Week 5 (Bounded Agent Workflow).

## 8. Conclusion

18 failure and authorization test cases were executed against the four
tools. The agent fails safely, refuses unauthorized actions, and complies
with the AI Boundary Matrix. Evidence is reproducible with:

```bash
python tests/run_tool_failure_tests.py