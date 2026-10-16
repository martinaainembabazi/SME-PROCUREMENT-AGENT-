"""
Week 5 & 7 — Bounded Agent Workflow & Observability
SME Procurement-Preparation Agent (CAC Supermarket, Kyanja)

Implements the Sense -> Plan -> Act -> Observe -> Stop loop defined in the
Agent Task Contract, with enhanced telemetry and robust transient error handling.
"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from orchestration import AppToolOrchestrator
from guardrail_service import (
    MAX_ITERATIONS,
    MAX_TOOL_CALLS,
    GuardrailService,
)
from prompt_loader import load_prompt

# Metadata constants for Week 7 tracking
MODEL_NAME = "gemini-2.5-flash"
PROMPT_VERSION = "v1.3"
TRACE_DIR = Path("evidence/traces")
TRACE_DIR.mkdir(parents=True, exist_ok=True)
@dataclass
class AgentRun:
    final_status: str
    iterations_used: int
    tool_calls_used: int
    steps: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str | None = None
    hand_off_reason: str | None = None


class ProcurementAgent:
    """Execute validated planner decisions under fixed iteration/tool limits."""

    def __init__(
        self,
        model_client: Any | None = None,
        orchestrator: AppToolOrchestrator | None = None,
        context_retriever: Callable[[str], Any] | None = None,
        *,
        max_iterations: int = MAX_ITERATIONS,
        max_tool_calls: int = MAX_TOOL_CALLS,
    ):
        if not 1 <= max_iterations <= MAX_ITERATIONS:
            raise ValueError(f"max_iterations must be between 1 and {MAX_ITERATIONS}.")
        if not 0 <= max_tool_calls <= MAX_TOOL_CALLS:
            raise ValueError(f"max_tool_calls must be between 0 and {MAX_TOOL_CALLS}.")
        self.guardrails = GuardrailService(
            max_iterations=max_iterations,
            max_tool_calls=max_tool_calls,
        )
        self.model_client = model_client
        self.orchestrator = orchestrator or AppToolOrchestrator()
        self.context_retriever = context_retriever
        self.max_iterations = self.guardrails.max_iterations
        self.max_tool_calls = self.guardrails.max_tool_calls
        self.system_prompt, self.user_template, self.prompt_version = load_prompt()

    def _generate(self, prompt: str) -> str:
        if self.model_client is None:
            from model_client import ModelClient

            self.model_client = ModelClient()
        return self.model_client.generate(
            prompt,
            system_instruction=self.system_prompt,
        )

    def _retrieve_context(self, question: str) -> Any:
        if self.context_retriever is None:
            from retriever import Retriever

            self.context_retriever = Retriever().retrieve
        return self.guardrails.validate_retrieved_documents(
            self.context_retriever(question)
        )

    def run(self, goal: str) -> AgentRun:
        goal = self.guardrails.validate_user_input(goal)
        steps: list[dict[str, Any]] = []
        tool_calls_used = 0
        last_observation: Any = None
        previous_tool_call: tuple[str, str] | None = None

        for iteration in range(1, self.max_iterations + 1):
            prompt = self.user_template.format(
                goal=goal,
                iteration=iteration,
                max_iterations=self.max_iterations,
                tool_calls_used=tool_calls_used,
                max_tool_calls=self.max_tool_calls,
                history=json.dumps(steps, ensure_ascii=False, default=str),
                last_observation=json.dumps(
                    last_observation, ensure_ascii=False, default=str
                ),
            )
            try:
                self.guardrails.validate_agent_context(
                    prompt, iteration, tool_calls_used
                )
            except ValueError as exc:
                return AgentRun(
                    final_status="BLOCKED_TOOL_FAILURE",
                    iterations_used=iteration,
                    tool_calls_used=tool_calls_used,
                    steps=steps,
                    hand_off_reason=str(exc),
                )
            try:
                raw_output = self._generate(prompt)
            except Exception as exc:
                steps.append({
                    "iteration": iteration,
                    "action": "planner",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                return AgentRun(
                    final_status="BLOCKED_TOOL_FAILURE",
                    iterations_used=iteration,
                    tool_calls_used=tool_calls_used,
                    steps=steps,
                    hand_off_reason="The planner model failed; human review is required.",
                )
            try:
                decision = self.guardrails.validate_planner_output(raw_output)
            except (ValueError, TypeError) as exc:
                steps.append({
                    "iteration": iteration,
                    "action": "parse_failure",
                    "error": str(exc),
                })
                return AgentRun(
                    final_status="BLOCKED_TOOL_FAILURE",
                    iterations_used=iteration,
                    tool_calls_used=tool_calls_used,
                    steps=steps,
                    hand_off_reason=f"Planner response was rejected: {exc}",
                )

            action = decision["action"]
            args = decision["args"]
            if action == "stop":
                try:
                    self.guardrails.validate_completion(args["final_status"], steps)
                except ValueError as exc:
                    steps.append({
                        "iteration": iteration,
                        "action": "parse_failure",
                        "error": str(exc),
                    })
                    return AgentRun(
                        final_status="BLOCKED_TOOL_FAILURE",
                        iterations_used=iteration,
                        tool_calls_used=tool_calls_used,
                        steps=steps,
                        hand_off_reason=str(exc),
                    )
                steps.append({
                    "iteration": iteration,
                    **decision,
                    "observation": "Planner stopped.",
                })
                return AgentRun(
                    final_status=args["final_status"],
                    iterations_used=iteration,
                    tool_calls_used=tool_calls_used,
                    steps=steps,
                    final_answer=args["final_answer"],
                )
            if action == "hand_off":
                steps.append({
                    "iteration": iteration,
                    **decision,
                    "observation": "Handed off to a human.",
                })
                return AgentRun(
                    final_status=args["final_status"],
                    iterations_used=iteration,
                    tool_calls_used=tool_calls_used,
                    steps=steps,
                    hand_off_reason=args["reason"],
                )

            serialized_args = json.dumps(args, sort_keys=True, ensure_ascii=False)
            call_identity = (action, serialized_args)
            if call_identity == previous_tool_call:
                steps.append({
                    "iteration": iteration,
                    **decision,
                    "error": "Repeated tool call was blocked by the runtime.",
                })
                return AgentRun(
                    final_status="BLOCKED_TOOL_FAILURE",
                    iterations_used=iteration,
                    tool_calls_used=tool_calls_used,
                    steps=steps,
                    hand_off_reason="Repeated tool call was blocked by the runtime.",
                )
            previous_tool_call = call_identity

            self.guardrails.authorize_tool(action, "agent")
            if tool_calls_used >= self.max_tool_calls:
                steps.append({
                    "iteration": iteration,
                    **decision,
                    "error": "The maximum tool-call limit was reached.",
                })
                return AgentRun(
                    final_status="BLOCKED_TOOL_FAILURE",
                    iterations_used=iteration,
                    tool_calls_used=tool_calls_used,
                    steps=steps,
                    hand_off_reason="The maximum tool-call limit was reached.",
                )

            tool_calls_used += 1
            try:
                if action == "retrieve_context":
                    observation = self._retrieve_context(args["question"])
                else:
                    observation = self.orchestrator.call_tool(
                        action,
                        args,
                        principal="agent",
                    )
            except Exception as exc:
                steps.append({
                    "iteration": iteration,
                    **decision,
                    "observation": None,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                return AgentRun(
                    final_status="BLOCKED_TOOL_FAILURE",
                    iterations_used=iteration,
                    tool_calls_used=tool_calls_used,
                    steps=steps,
                    hand_off_reason="An approved tool failed; human review is required.",
                )

            steps.append({
                "iteration": iteration,
                **decision,
                "observation": observation,
            })
            last_observation = observation

        return AgentRun(
            final_status="BLOCKED_TOOL_FAILURE",
            iterations_used=self.max_iterations,
            tool_calls_used=tool_calls_used,
            steps=steps,
            hand_off_reason="The maximum agent-iteration limit was reached.",
        )


def save_trace(run: AgentRun, output_path: str | Path) -> None:
    """Persist the bounded run summary for later review."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(run), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


class AgentRunner:
    def __init__(self, goal: str, scenario_id: str = None):
        self.run_id = str(uuid.uuid4())
        self.scenario_id = scenario_id or "adhoc_run"
        self.goal = goal
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.steps = []
        self.guardrail_events = []
        self.retry_count = 0

    def log_step(
        self,
        iteration: int,
        thought: str,
        action: str,
        args: dict,
        observation: Any,
        error: str = None,
        raw_output: str = None,
        step_latency_sec: float = 0.0,
    ):
        step_data = {
            "iteration": iteration,
            "thought": thought,
            "action": action,
            "args": args,
            "observation": observation,
            "error": error,
            "raw_model_output": raw_output,
            "per_step_latency_sec": round(step_latency_sec, 3),
        }
        self.steps.append(step_data)

    def log_guardrail(self, event_type: str, details: str):
        self.guardrail_events.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "details": details,
        })

    def finalize(self, final_status: str, final_answer: str = None, hand_off_reason: str = None):
        completed_at = datetime.now(timezone.utc).isoformat()
        trace_record = {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "model_name": MODEL_NAME,
            "prompt_version": PROMPT_VERSION,
            "started_at": self.started_at,
            "completed_at": completed_at,
            "final_status": final_status,
            "iterations_used": len(self.steps),
            "tool_calls_used": sum(1 for s in self.steps if s["action"] not in ["parse_failure", "done", "none"]),
            "retry_count": self.retry_count,
            "guardrail_events": self.guardrail_events,
            "final_answer": final_answer,
            "hand_off_reason": hand_off_reason,
            "steps": self.steps,
        }

        # Write to individual JSON file per run in evidence/traces/
        filename = TRACE_DIR / f"trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.run_id[:8]}.json"
        filename.write_text(json.dumps(trace_record, indent=2))
        print(f"[Trace Saved] -> {filename}")
        return trace_record


def invoke_model_with_retry(model_client, prompt, tracer: AgentRunner, max_retries=3):
    """Safely invokes the LLM client while handling 429 ResourceExhausted errors via backoff."""
    retries = 0
    while retries < max_retries:
        start_time = time.time()
        try:
            response = model_client.generate_content(prompt)
            return response, time.time() - start_time
        except Exception as e:
            if (
                type(e).__name__ != "ResourceExhausted"
                and getattr(e, "code", None) != 429
                and getattr(e, "status_code", None) != 429
            ):
                raise
            retries += 1
            tracer.retry_count += 1
            tracer.log_guardrail("rate_limit_429", str(e))
            if retries >= max_retries:
                # Re-raise if all retries exhausted so it logs properly as a tool/model failure
                raise e
            backoff_time = 10 * retries
            print(f"[Rate Limit] Quota exceeded. Backing off for {backoff_time}s (Retry {retries}/{max_retries})...")
            time.sleep(backoff_time)
