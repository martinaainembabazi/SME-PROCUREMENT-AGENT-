"""Validation helpers shared by the agent runtime and application tools."""

from __future__ import annotations

import json
from typing import Any

MAX_USER_INPUT_LENGTH = 4_000
MAX_MODEL_OUTPUT_LENGTH = 20_000
MAX_TOOL_TEXT_LENGTH = 1_000
MAX_DRAFT_QUANTITY = 1_000_000

FINAL_STATUSES = {
    "COMPLETED_PENDING_HUMAN_REVIEW",
    "COMPLETED_NO_REORDER",
    "BLOCKED_MISSING_INFORMATION",
    "BLOCKED_TOOL_FAILURE",
    "STOPPED_OUT_OF_SCOPE",
    "WAITING_FOR_HUMAN_APPROVAL",
}

TOOL_ACTIONS = {
    "retrieve_context",
    "get_inventory_snapshot",
    "get_reorder_candidates",
    "compare_supplier_quotes",
    "create_draft_requisition",
}

def validate_text(
    value: Any,
    field: str,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    text = value.strip()
    if not text and not allow_empty:
        raise ValueError(f"{field} is required.")
    if len(text) > maximum:
        raise ValueError(f"{field} exceeds the maximum length of {maximum}.")
    if any(ord(char) < 32 and char not in "\n\t\r" for char in text):
        raise ValueError(f"{field} contains unsupported control characters.")
    return text

def validate_user_input(value: Any) -> str:
    return validate_text(value, "user input", maximum=MAX_USER_INPUT_LENGTH)

def validate_model_answer(value: Any) -> str:
    return validate_text(value, "model answer", maximum=MAX_MODEL_OUTPUT_LENGTH)

def _validate_item_code(value: Any, field: str = "item_code") -> str:
    text = validate_text(value, field, maximum=64)
    if any(ord(char) < 32 for char in text):
        raise ValueError(f"{field} contains unsupported control characters.")
    return text

def _validate_optional_item_code(args: dict[str, Any]) -> None:
    if "item_code" not in args or args["item_code"] is None:
        args["item_code"] = None
    else:
        args["item_code"] = _validate_item_code(args["item_code"])

def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Planner output contains duplicate key '{key}'.")
        result[key] = value
    return result

def validate_decision(raw_output: Any) -> dict[str, Any]:
    """Parse and validate one planner response; reject extra keys and actions."""
    if not raw_output or "[MODEL ERROR]" in str(raw_output):
        raise RuntimeError(f"API Failure: {raw_output}")
    raw = validate_text(raw_output, "planner output", maximum=MAX_MODEL_OUTPUT_LENGTH)
    
    raw = raw.strip()
    start_idx = raw.find('{')
    end_idx = raw.rfind('}')
    
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        raw = raw[start_idx:end_idx+1]

    try:
        decision = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ValueError("Planner output must be a single JSON object.") from exc

    if not isinstance(decision, dict) or set(decision) != {"thought", "action", "args"}:
        raise ValueError("Planner decision must contain only thought, action, and args.")

    thought = validate_text(decision["thought"], "thought", maximum=500)
    action = decision["action"]
    args = decision["args"]
    if not isinstance(action, str) or not isinstance(args, dict):
        raise ValueError("Planner action must be a string and args must be an object.")

    if action in TOOL_ACTIONS:
        if action == "retrieve_context":
            if set(args) != {"question"}:
                raise ValueError("retrieve_context requires only a question.")
            args["question"] = validate_text(args["question"], "question", maximum=MAX_USER_INPUT_LENGTH)
        elif action in {"get_inventory_snapshot", "get_reorder_candidates"}:
            if set(args) - {"item_code"}:
                raise ValueError(f"{action} accepts only item_code.")
            _validate_optional_item_code(args)
        elif action == "compare_supplier_quotes":
            if set(args) != {"item_code"}:
                raise ValueError("compare_supplier_quotes requires only item_code.")
            args["item_code"] = _validate_item_code(args["item_code"])
        else:
            allowed = {"item_code", "quantity", "supplier_name", "notes"}
            required = {"item_code", "quantity", "supplier_name"}
            if required - set(args) or set(args) - allowed:
                raise ValueError("create_draft_requisition has missing or unsupported arguments.")
            args["item_code"] = _validate_item_code(args["item_code"])
            quantity = args["quantity"]
            if isinstance(quantity, bool) or not isinstance(quantity, int):
                raise ValueError("quantity must be an integer.")
            if quantity <= 0 or quantity > MAX_DRAFT_QUANTITY:
                raise ValueError(f"quantity must be between 1 and {MAX_DRAFT_QUANTITY}.")
            args["supplier_name"] = validate_text(args["supplier_name"], "supplier_name", maximum=120)
            args["notes"] = validate_text(args.get("notes", ""), "notes", maximum=MAX_TOOL_TEXT_LENGTH, allow_empty=True)
    elif action == "stop":
        if set(args) != {"final_status", "final_answer"}:
            raise ValueError("stop requires final_status and final_answer.")
        if not isinstance(args["final_status"], str) or args["final_status"] not in FINAL_STATUSES:
            raise ValueError("stop contains an unsupported final_status.")
        if args["final_status"] in {"STOPPED_OUT_OF_SCOPE", "WAITING_FOR_HUMAN_APPROVAL"}:
            raise ValueError("This final_status requires a hand_off action.")
        args["final_answer"] = validate_text(args["final_answer"], "final_answer", maximum=6_000)
    elif action == "hand_off":
        if set(args) != {"final_status", "reason"}:
            raise ValueError("hand_off requires final_status and reason.")
        if not isinstance(args["final_status"], str) or args["final_status"] not in FINAL_STATUSES:
            raise ValueError("hand_off contains an unsupported final_status.")
        if args["final_status"] in {"COMPLETED_PENDING_HUMAN_REVIEW", "COMPLETED_NO_REORDER"}:
            raise ValueError("A completion final_status requires a stop action.")
        args["reason"] = validate_text(args["reason"], "reason", maximum=2_000)
    else:
        raise ValueError(f"Planner action '{action}' is not allowed.")

    return {"thought": thought, "action": action, "args": args}