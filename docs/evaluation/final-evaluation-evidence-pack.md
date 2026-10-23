# Final Evaluation and Evidence Pack

**Project:** SME Procurement-Preparation Agent  
**Evaluation date:** 2026-10-23  
**Repository revision:** `7759f4e`  
**Overall verdict:** **CONDITIONAL PASS** — deterministic application and authorization checks pass; model-backed and end-to-end validation remains outstanding.

## 1. Evaluation scope

This evaluation uses the project scope described in the [README](../../README.md): read inventory, identify reorder candidates, compare supplier quotations, prepare draft requisitions, and keep approval and purchasing decisions with a human. Data in the repository is synthetic/team-created.

The repository does not contain a formal feature specification, implementation plan, constitution, or modernization checkpoints. Accordingly, this is a project-level evaluation and evidence summary, not certification of a formal completeness-gate workflow. No explicit P1 list was available; the core workflow and human-authorization boundary were treated as the principal acceptance areas.

## 2. Results at a glance

| Check | Result | Evidence |
|---|---|---|
| Python unit and service tests | **PASS — 41/41** | Command and output summarized below; three `test_*.py` modules |
| Python source compilation | **PASS** | `python -m compileall -q src tests` |
| Inventory, reorder, and quote operations | **PASS** | Deterministic orchestration and data-store tests |
| Draft requisition and approval boundary | **PASS** | Requisition lifecycle and security-control tests |
| Role, approval-threshold, MOQ, and quote requirements | **PASS** | MVP service tests |
| Historical failure/authorization suite | **PASS — 18/18 recorded** | [Week 4 results](../../evidence/week4_tool_failure_results.json); pre-existing evidence, not rerun in this evaluation |
| Supplier-memory demonstrations | **RECORDED — 5 scenarios** | [Memory demo summary](../../evidence/traces/memory_demo_summary.json); pre-existing evidence |
| Live model-backed workflow | **PARTIAL** | Existing traces include successful draft flows and safe failures; two 2026-10-13 traces show Gemini `503 UNAVAILABLE` |
| Week 7, 30-scenario evaluation set | **NOT RUN** | [Evaluation dataset](../../tests/week7_evaluation.json) contains cases but no execution results were produced in this evaluation |
| RAG evaluation | **NOT RUN** | Existing evaluation materials were not re-executed |
| Browser/UI end-to-end smoke test | **NOT RUN** | No browser run was performed in this evaluation |

## 3. Reproducible checks performed

### Unit and service tests

Executed from the repository root with the project virtual environment:

```powershell
& 'C:\Users\USER\SME-PROCUREMENT-AGENT-\venv\Scripts\python.exe' -m unittest discover -s tests -p 'test_*.py' -v
```

**Result:** 41 tests passed, 0 failed, in 14.923 seconds. Coverage includes authentication and role rules, inventory/quotation validation and updates, requisition lifecycle and approval constraints, tool orchestration, bounded agent behavior, malformed model output, safe completion requirements, and prohibited actions.

### Python compilation

Executed:

```powershell
& 'C:\Users\USER\SME-PROCUREMENT-AGENT-\venv\Scripts\python.exe' -m compileall -q src tests
```

**Result:** exit code 0.

This Python project has no conventional compiled build command in the repository. Compilation is a syntax check and is not represented as a full application build or a UI startup test.

## 4. Requirement-to-evidence mapping

| Core behavior | Result | Evidence and limit |
|---|---|---|
| Read inventory and determine reorder status from current stock and thresholds | **PASS** | `test_tool_orchestration.py`, `test_mvp_services.py`; historical agent traces include inventory retrieval |
| Compare supplier quotations using available records | **PASS** | `test_tool_orchestration.py` and data-store tests; this verifies deterministic tool behavior, not model answer quality |
| Create a draft requisition and leave it pending human approval | **PASS** | Orchestration and security tests assert saved drafts remain `pending_human_approval`, including notes attempting to override approval |
| Prevent the agent from approving, ordering, or paying | **PASS** | Guardrail/tool allow-list and authorization tests; historical Week 4 failure/authorization report records 18/18 cases passed |
| Enforce human roles, approval limits, quote/payment-term requirements, and MOQ | **PASS** | `test_mvp_services.py` covers roles, manager threshold, missing quote/payment terms, MOQ, rejection, and lifecycle |
| Update stock and supplier memory through the human-controlled requisition lifecycle | **PASS** | Requisition lifecycle test; separate stored memory-demo evidence has five scenarios |
| Validate grounded RAG/model responses and adversarial prompts across the evaluation set | **NOT ESTABLISHED** | The 30-case evaluation dataset exists, but a corresponding scored run was not produced here |
| Demonstrate a successful live model workflow under current service conditions | **PARTIAL** | Stored traces include successful draft completions; two October 13 traces record a 503 after inventory retrieval and correctly end as `BLOCKED_TOOL_FAILURE` |

## 5. Existing evidence inventory

- [Unit and service tests](../../tests/) — three test modules; current run passed 41/41.
- [Week 4 failure/authorization results](../../evidence/week4_tool_failure_results.json) — stored report states 18 total, 18 passed, 0 failed. This is historical evidence and was not regenerated.
- [Agent execution traces](../../evidence/traces/) — 12 `trace_*.json` files were readable. Their recorded statuses comprise four completed-pending-review traces, five blocked-tool-failure traces, two blocked-missing-information traces, and one out-of-scope handoff. These are a mixture of scenarios and service conditions, not a pass-rate.
- [Supplier memory demonstrations](../../evidence/traces/memory_demo_summary.json) — five documented scenarios covering post-approval write, reuse, live quote comparison, rejected drafts, and missing/unreadable memory.
- [Week 7 evaluation set](../../tests/week7_evaluation.json) — 30 scenarios spanning normal use, edge cases, incorrect information, adversarial input, tool failure, and unauthorized actions; execution results are not included in this pack.
- [Failure catalogue](./failure_catalogue.md) — records open retesting needs, including service failure, unsupported claims, fabricated comparisons, authorization, invalid input, prompt injection, and tool failure.

## 6. Findings and remaining work

| ID | Severity | Finding | Evidence / recommended action |
|---|---|---|---|
| F-01 | **HIGH** | Live model completion is not reliable enough to claim end-to-end pass. Existing October 13 traces show `503 UNAVAILABLE` after an inventory tool call; the application stopped safely, but did not complete the user task. | Preserve the fail-safe behavior. Repeat representative live runs when the model service is available and record the exact result; do not treat a safe stop as task completion. |
| F-02 | **HIGH** | The 30-case Week 7 evaluation dataset has no execution report in this evaluation. | Run the cases against a controlled, reproducible setup; save per-case expected/observed outcomes and aggregate scores, including adversarial and failure cases. |
| F-03 | **MEDIUM** | RAG quality and browser/UI behavior were not verified in this evaluation. | Run the existing RAG evaluation and a browser smoke test, and retain the resulting reports/screenshots. |
| F-04 | **LOW** | The README status text still says “Week 1 of 8” while also describing the Week 8 MVP. | Update the status wording when the team confirms the final project milestone. |

## 7. Release interpretation

The deterministic service and safety controls passed the tests executed for this pack. In particular, the agent's tool boundary and pending-human-approval state are enforced by tests. The stored traces also show that model-service failure is surfaced as a blocked operation rather than a successful procurement result.

The evidence does **not** establish full model-response quality, current live-service availability, RAG quality, or end-to-end browser behavior. Therefore, this pack supports a **conditional pass for deterministic core behavior**, not an unconditional end-to-end or production-readiness claim. Complete F-01 through F-03 before presenting model-backed procurement outcomes as fully evaluated.
