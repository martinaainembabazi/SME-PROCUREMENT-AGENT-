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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.api_core.exceptions import ResourceExhausted

# Metadata constants for Week 7 tracking
MODEL_NAME = "gemini-2.5-flash"
PROMPT_VERSION = "v1.2"
TRACE_DIR = Path("evidence/traces")
TRACE_DIR.mkdir(parents=True, exist_ok=True)


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
        except ResourceExhausted as e:
            retries += 1
            tracer.retry_count += 1
            tracer.log_guardrail("rate_limit_429", str(e))
            if retries >= max_retries:
                # Re-raise if all retries exhausted so it logs properly as a tool/model failure
                raise e
            backoff_time = 10 * retries
            print(f"[Rate Limit] Quota exceeded. Backing off for {backoff_time}s (Retry {retries}/{max_retries})...")
            time.sleep(backoff_time)
