# Agent Architecture — SME Procurement Preparation Agent

**Week 5 Deliverable · Group D**

## Bounded Loop (Sense → Plan → Act → Observe → Stop)

┌──────────────────────────────────────────────┐
│ Agent Task Contract                          │
│ Goal: prepare procurement recommendation     │
│ and draft requisition for review             │
└──────────────────────┬───────────────────────┘
│
┌────────────────▼─────────────────┐
│ SENSE (context)                  │
│ - user request                   │
│ - step history                   │
│ - last observation               │
│ - iteration & tool-call counters │
└────────────────┬─────────────────┘
│
┌────────────────▼─────────────────┐
│ PLAN (Planner prompt v1.2)       │
│ Model returns JSON decision      │
└────────────────┬─────────────────┘
│
┌────────────────▼─────────────────┐
│ ACT (execute chosen action)      │
│ retrieve_context | 4 tools       │     
│ stop          | hand_off         │
└────────────────┬─────────────────┘
│
┌────────────────▼─────────────────┐
│ OBSERVE (record result)          │
│ - observation / error            │
│ - increment counters             │
└────────────────┬─────────────────┘
│
┌────────────────▼─────────────────┐
│ STOP GUARDS                      │
│ 1. stop / hand_off               │
│ 2. max iterations (8)            │
│ 3. max tool calls (12)           │
│ 4. repeated action detected      │
│ 5. unknown action                │
└────────────────┬─────────────────┘
│
┌────────────┴────────────┐
│ continue (loop) │ stop → final_status
└─────────────────────────┘


## Components

| Component | File | Role |
|---|---|---|
| Planner prompt | `prompts/sme_procurement/v1.2_planner_*.txt` | Instructs model to return JSON decisions |
| Model client | `src/model_client.py` | Calls Gemini |
| Agent loop | `src/agent.py` | Implements Sense/Plan/Act/Observe/Stop |
| Orchestrator | `src/orchestration.py` | Executes the 4 approved tools |
| RAG pipeline | `src/rag.py` | Provides grounded context |
| Trace logger | `src/agent.py:save_trace` | Writes JSON traces to `evidence/traces/` |

## Limits (from Agent Task Contract §6)

- Max workflow iterations: **8**
- Max tool calls: **12**
- Max retries per tool: **2**

## Stop Conditions (from Agent Task Contract §7)

- Explicit `stop` from planner
- Explicit `hand_off` from planner
- Iteration limit reached
- Tool-call limit reached
- Repeated action detected
- Unknown action chosen

## Final Statuses (from Agent Task Contract §10)

- COMPLETED_PENDING_HUMAN_REVIEW
- COMPLETED_NO_REORDER
- BLOCKED_MISSING_INFORMATION
- BLOCKED_TOOL_FAILURE
- STOPPED_OUT_OF_SCOPE
- WAITING_FOR_HUMAN_APPROVAL

## Human Hand-off Boundaries

The agent's authority ends at procurement **preparation**:

- ✅ May read inventory, reorder candidates, supplier quotes
- ✅ May create a **draft** requisition (status = `pending_human_approval`)
- ❌ May **not** approve a purchase
- ❌ May **not** place an order
- ❌ May **not** execute or authorize payment