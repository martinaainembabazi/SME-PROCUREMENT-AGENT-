"""
Week 5 — Run agent traces for the three required scenarios.
Produces evidence/traces/trace_01_success.json, trace_02_failure_recovery.json, trace_03_hand_off.json
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent import ProcurementAgent, save_trace  # noqa: E402


SCENARIOS_PATH = ROOT / "tests" / "agent_scenarios.json"
TRACES_DIR = ROOT / "evidence" / "traces"


def main():
    scenarios = json.loads(SCENARIOS_PATH.read_text())

    for scenario in scenarios:
        print("=" * 70)
        print(f"[{scenario['id']}] {scenario['description']}")
        print(f"Goal: {scenario['goal']}")
        print("-" * 70)

        agent = ProcurementAgent()
        run = agent.run(scenario["goal"])

        out_path = TRACES_DIR / f"{scenario['id']}.json"
        save_trace(run, out_path)

        passed = run.final_status in scenario["expected_status_in"]
        print(f"Status:        {run.final_status}")
        print(f"Iterations:    {run.iterations_used}")
        print(f"Tool calls:    {run.tool_calls_used}")
        print(f"Expected in:   {scenario['expected_status_in']}")
        print(f"Result:        {'PASS' if passed else 'FAIL'}")
        print(f"Trace saved:   {out_path}")
        print()

        # Extra detailed dump for success trace
        if scenario["id"] == "trace_01_success":
            print("--- STEP LOG ---")
            for s in run.steps:
                print(f"  [{s.iteration}] {s.action}  args={s.args}")
            print()


if __name__ == "__main__":
    main()