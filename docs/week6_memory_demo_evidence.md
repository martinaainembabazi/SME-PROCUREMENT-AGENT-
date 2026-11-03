# Week 6 — Working Memory / State Demonstration

**Project:** SME Procurement-Preparation Agent (CAC Supermarket, Kyanja)
**Team:** Group D
**Week:** 6
**Author:** Joel T., Application/Integration Lead
**Date:** 2026-10-09

---

## 1. Purpose

This document provides evidence that the SME Procurement-Preparation
Agent implements the persistent-memory design in
`docs/requirements/Memory design and data handling note.docx`.

## 2. Scope

The demonstration covers the five scenarios in Section 8 of the
Memory Design note:

| # | Scenario | Expected |
|---|---|---|
| 1 | First request; no record; human approves | No pre-fill; record written after approval |
| 2 | Same item again | Approved supplier pre-filled with source label |
| 3 | Cheaper supplier now quoted | Both shown; human still decides; memory does not override |
| 4 | Draft rejected / changes required | Nothing written to memory |
| 5 | Memory file missing or unreadable | Agent drafts normally; reports no preference found |

## 3. Implementation Summary

| Component | File |
|---|---|
| `MemoryStore` class | `src/memory.py` |
| Memory file | `evidence/memory/approved_supplier_memory.json` |
| Audit log | `evidence/memory/memory_log.jsonl` |
| Demonstration runner | `tests/run_memory_demo.py` |

**Storage:** single local JSON file, one record per item_code.
**Write path:** orchestration layer only, triggered by recorded human approval.
**Read path:** agent, at drafting step, once per item per run.
**Retention:** replacement on new approval; stale flag at 90 days.

## 4. Results

Full traces: `evidence/traces/memory_demo_*.json`.

### Scenario 1 — First request, human approves
- Before approval: no pre-fill (memory empty for CEM50).
- After human approval: record written with supplier name, draft ID, approver, timestamp.
- **Trace:** `evidence/traces/memory_demo_1_first_request_no_record_human_approves.json`

### Scenario 2 — Same item again
- Memory read returns the approved supplier.
- Pre-fill label produced: `"last approved on <date>, draft <id>"`.
- **Trace:** `evidence/traces/memory_demo_2_same_item_again.json`

### Scenario 3 — Cheaper supplier now quoted
- Memory returns the remembered supplier.
- Live `compare_supplier_quotes` runs and returns current quotes.
- **Both shown; memory does not override** — verified by inspection of the trace.
- **Trace:** `evidence/traces/memory_demo_3_cheaper_supplier_now_quoted.json`

### Scenario 4 — Draft rejected
- No approval recorded → no write.
- Memory remains unchanged.
- **Trace:** `evidence/traces/memory_demo_4_draft_rejected_no_write.json`

### Scenario 5 — Memory file unreadable
- Corrupted file → `_load()` catches JSONDecodeError → returns empty.
- Agent drafts normally and reports no preference found.
- **Trace:** `evidence/traces/memory_demo_5_memory_missing_or_unreadable.json`

## 5. Memory Log

Every read and write is recorded in `evidence/memory/memory_log.jsonl`.

Sample events:

| Timestamp (UTC) | Event | Item | Detail |
|---|---|---|---|
| ... | read_miss | CEM50 | no_record |
| ... | write | CEM50 | supplier=Supplier A draft=DR-... by=Procurement Officer |
| ... | read_hit | CEM50 | supplier=Supplier A |
| ... | read_stale | ... | (if applicable) |

## 6. Safeguards Verified

| Safeguard (from Memory Design note §7) | Verified? | Evidence |
|---|---|---|
| Advisory only — memory never finalizes | ✅ | Scenario 3: live data still decides |
| Live data decides — quotes run before memory read | ✅ | Scenario 3 trace shows quotes and memory both present |
| Approval gate unchanged | ✅ | All drafts remain `pending_human_approval` |
| Fail safe on missing/unreadable memory | ✅ | Scenario 5 |
| Data, not instructions | ✅ | Memory fields used as values, not prompts |
| Logging | ✅ | `memory_log.jsonl` populated |

## 7. Known Limitations

- The demonstration is script-driven; the five scenarios are simulated by the runner.
- In real operation, the write step requires an explicit human approval action
  (not yet wired into a UI; tracked as Week 8 hardening work).
- Concurrent writes are not tested this week.

## 8. Conclusion

All five scenarios from the Memory Design note pass. Persistent memory
improves a legitimate task (pre-fills a settled supplier choice) without
overriding live data or approval gates. Memory is written only after
human approval, and fails safely when missing or stale.

## 9. Evidence Files

- `src/memory.py`
- `tests/run_memory_demo.py`
- `evidence/traces/memory_demo_*.json`
- `evidence/memory/approved_supplier_memory.json`
- `evidence/memory/memory_log.jsonl`
- `evidence/screenshots/week6_memory_demo.png`