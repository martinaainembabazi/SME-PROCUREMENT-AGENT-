"""
Week 5 — Bounded Agent Workflow
SME Procurement-Preparation Agent (CAC Supermarket, Kyanja)

Implements the Sense -> Plan -> Act -> Observe -> Stop loop defined in the
Agent Task Contract (Week 5).
"""
from __future__ import annotations

import json
import re
import sys
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from model_client import ModelClient              # noqa: E402
from orchestration import AppToolOrchestrator     # noqa: E402
from prompt_loader import load_prompt             # noqa: E402
from rag import RAGPipeline                       # noqa: E402


# --- Limits from the Agent Task Contract ---
MAX_ITERATIONS = 8
MAX_TOOL_CALLS = 12
MAX_RETRIES_PER_TOOL = 2

TOOL_ACTIONS = {
    "get_inventory_snapshot",
    "get_reorder_candidates",
    "compare_supplier_quotes",
    "create_draft_requisition",
}

VALID_STATUSES = {
    "COMPLETED_PENDING_HUMAN_REVIEW",
    "COMPLETED_NO_REORDER",
    "BLOCKED_MISSING_INFORMATION",
    "BLOCKED_TOOL_FAILURE",
    "STOPPED_OUT_OF_SCOPE",
    "WAITING_FOR_HUMAN_APPROVAL",
}

# Words that indicate the user (or model) is trying to cross a boundary.
PROHIBITED_TERMS = [
    "approve the last draft",
    "approve requisition",
    "approve the requisition",
    "send payment",
    "make payment",
    "execute payment",
    "place the order",
    "place an order",
    "pay supplier",
    "pay the supplier",
    "finalize the purchase",
    "finalize purchase",
    "authorize payment",
    "authorise payment",
]


@dataclass
class Step:
    iteration: int
    thought: str
    action: str
    args: dict
    observation: Any
    error: str | None = None
    raw_model_output: str | None = None   # NEW: keep the raw model text for debugging


@dataclass
class AgentRun:
    goal: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    final_status: str | None = None
    final_answer: str | None = None
    hand_off_reason: str | None = None
    iterations_used: int = 0
    tool_calls_used: int = 0
    steps: list[Step] = field(default_factory=list)


class ProcurementAgent:
    """Bounded agent loop aligned to the Week 5 Agent Task Contract."""

    def __init__(
        self,
        model_client: ModelClient | None = None,
        orchestrator: AppToolOrchestrator | None = None,
        rag: RAGPipeline | None = None,
        prompt_version: str = "v1.2",
    ):
        self.model = model_client or ModelClient()
        self.orchestrator = orchestrator or AppToolOrchestrator()
        self.rag = rag or RAGPipeline()
        self.prompt_version = prompt_version

    # ---------------- Public API ----------------

    def run(self, goal: str) -> AgentRun:
        run = AgentRun(goal=goal)
        system_prompt, user_template, version = load_prompt(self.prompt_version)

        # --- Pre-flight: obvious out-of-scope request → hand off immediately ---
        lowered = goal.lower()
        if any(term in lowered for term in PROHIBITED_TERMS):
            run.final_status = "STOPPED_OUT_OF_SCOPE"
            run.hand_off_reason = (
                "The request asks for an action outside the agent's permitted role "
                "(order approval, payment, or order placement). Human action is required."
            )
            run.completed_at = datetime.now(timezone.utc).isoformat()
            return run

        while True:
            if run.iterations_used >= MAX_ITERATIONS:
                run.final_status = "BLOCKED_TOOL_FAILURE"
                run.final_answer = (
                    f"Reached max iterations ({MAX_ITERATIONS}) without a definitive answer."
                )
                break

            history_text = self._format_history(run.steps)
            last_obs = run.steps[-1].observation if run.steps else "None yet"

            user_prompt = user_template.format(
                goal=goal,
                iteration=run.iterations_used + 1,
                max_iterations=MAX_ITERATIONS,
                tool_calls_used=run.tool_calls_used,
                max_tool_calls=MAX_TOOL_CALLS,
                history=history_text,
                last_observation=self._short(last_obs),
            )

            raw = self.model.generate(prompt=user_prompt, system_instruction=system_prompt)
            decision = self._parse_decision(raw)

            if decision is None:
                # If the model responded with prose that mentions prohibited terms,
                # treat it as out-of-scope rather than a generic failure.
                if any(term in (raw or "").lower() for term in PROHIBITED_TERMS):
                    run.final_status = "STOPPED_OUT_OF_SCOPE"
                    run.hand_off_reason = (
                        "Planner output referenced a prohibited action; escalating to human."
                    )
                else:
                    run.final_status = "BLOCKED_TOOL_FAILURE"
                    run.final_answer = f"Planner returned unparseable output: {(raw or '')[:200]}"
                run.steps.append(
                    Step(run.iterations_used + 1, "", "parse_failure", {}, None,
                         error="unparseable_output", raw_model_output=raw)
                )
                run.iterations_used += 1
                break

            thought = decision.get("thought", "")
            action = decision.get("action", "")
            args = decision.get("args", {}) or {}

            # --- stop ---
            if action == "stop":
                status = args.get("final_status", "COMPLETED_NO_REORDER")
                if status not in VALID_STATUSES:
                    status = "COMPLETED_NO_REORDER"
                run.final_status = status
                run.final_answer = args.get("final_answer", "")
                run.steps.append(
                    Step(run.iterations_used + 1, thought, action, args, None,
                         raw_model_output=raw)
                )
                run.iterations_used += 1
                break

            # --- hand_off ---
            if action == "hand_off":
                status = args.get("final_status", "WAITING_FOR_HUMAN_APPROVAL")
                if status not in VALID_STATUSES:
                    status = "WAITING_FOR_HUMAN_APPROVAL"
                run.final_status = status
                run.hand_off_reason = args.get("reason", "")
                run.steps.append(
                    Step(run.iterations_used + 1, thought, action, args, None,
                         raw_model_output=raw)
                )
                run.iterations_used += 1
                break

            # --- unknown action ---
            if action not in TOOL_ACTIONS and action != "retrieve_context":
                run.final_status = "STOPPED_OUT_OF_SCOPE"
                run.final_answer = f"Planner chose unknown action '{action}'."
                run.steps.append(
                    Step(run.iterations_used + 1, thought, action, args, None,
                         error="unknown_action", raw_model_output=raw)
                )
                run.iterations_used += 1
                break

            # --- tool-call limit ---
            if action in TOOL_ACTIONS and run.tool_calls_used >= MAX_TOOL_CALLS:
                run.final_status = "BLOCKED_TOOL_FAILURE"
                run.final_answer = f"Reached max tool calls ({MAX_TOOL_CALLS})."
                break

            # --- repeated-action guard: only trip when the previous call succeeded ---
            if run.steps:
                prev = run.steps[-1]
                if prev.action == action and prev.args == args and prev.error is None:
                    run.final_status = "BLOCKED_TOOL_FAILURE"
                    run.final_answer = (
                        f"Planner repeated '{action}' with identical args; aborting to avoid a loop."
                    )
                    break

            # --- execute ---
            observation, error = self._execute(action, args)
            run.steps.append(
                Step(run.iterations_used + 1, thought, action, args, observation, error,
                     raw_model_output=raw)
            )
            run.iterations_used += 1
            if action in TOOL_ACTIONS:
                run.tool_calls_used += 1

        run.completed_at = datetime.now(timezone.utc).isoformat()
        return run

    # ---------------- Execution ----------------

    def _execute(self, action: str, args: dict) -> tuple[Any, str | None]:
        if action == "retrieve_context":
            try:
                question = args.get("question", "")
                result = self.rag.generate_answer(question, top_k=5)
                return {"answer": result.get("answer"), "sources": result.get("sources", [])}, None
            except Exception as e:
                return None, f"{type(e).__name__}: {e}"

        last_error = None
        for attempt in range(1, MAX_RETRIES_PER_TOOL + 2):
            try:
                result = self.orchestrator.call_tool(action, args)
                return result, None
            except Exception as e:
                last_error = f"{type(e).__name__}: {e} (attempt {attempt})"
        return None, last_error

    # ---------------- Helpers ----------------

    def _parse_decision(self, raw: str) -> dict | None:
        if not raw:
            return None
        text = raw.strip()

        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        else:
            brace = re.search(r"\{.*\}", text, re.DOTALL)
            if brace:
                text = brace.group(0)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _format_history(self, steps: list[Step]) -> str:
        if not steps:
            return "(no steps yet)"
        lines = []
        for s in steps:
            obs = self._short(s.observation)
            lines.append(f"{s.iteration}. [{s.action}] args={s.args} -> {obs}")
        return "\n".join(lines)

    def _short(self, value: Any, limit: int = 300) -> str:
        try:
            text = json.dumps(value, default=str)
        except Exception:
            text = str(value)
        return text if len(text) <= limit else text[:limit] + "..."


# ---------------- CLI / trace saver ----------------

def save_trace(run: AgentRun, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(run)
    data["steps"] = [asdict(s) for s in run.steps]
    path.write_text(json.dumps(data, indent=2, default=str))


def main():
    if len(sys.argv) < 2:
        print("Usage: python src/agent.py \"<your procurement question>\"")
        sys.exit(1)

    goal = " ".join(sys.argv[1:])
    agent = ProcurementAgent()

    print(f"\n[AGENT] Goal: {goal}\n")
    run = agent.run(goal)

    print(f"[STATUS] {run.final_status}")
    print(f"[ITERATIONS] {run.iterations_used}  |  [TOOL CALLS] {run.tool_calls_used}")
    if run.final_answer:
        print(f"\n[FINAL ANSWER]\n{run.final_answer}")
    if run.hand_off_reason:
        print(f"\n[HAND-OFF REASON]\n{run.hand_off_reason}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "evidence" / "traces" / f"trace_{ts}.json"
    save_trace(run, out)
    print(f"\n[trace saved] {out}")


if __name__ == "__main__":
    main()