"""Central guardrail policy for input, model, tool, and agent-loop boundaries."""

from __future__ import annotations

import json
import re
from typing import Any

from security import (
    MAX_DRAFT_QUANTITY,
    validate_decision,
    validate_model_answer,
    validate_text,
    validate_user_input,
)


MAX_ITERATIONS = 8
MAX_TOOL_CALLS = 12
MAX_AGENT_PROMPT_LENGTH = 250_000
MAX_TOOL_RESULT_LENGTH = 1_000_000
MAX_RETRIEVED_DOCUMENTS = 10
MAX_RETRIEVED_TEXT_LENGTH = 20_000

READ_ONLY_TOOLS = frozenset({
    "get_inventory_snapshot",
    "get_reorder_candidates",
    "compare_supplier_quotes",
    "retrieve_context",
})
TOOL_ROLES = {
    "agent": READ_ONLY_TOOLS | {"create_draft_requisition"},
    "viewer": READ_ONLY_TOOLS,
}
ALL_TOOLS = frozenset().union(*TOOL_ROLES.values())


def _validate_single_line(value: Any, field: str, maximum: int) -> str:
    text = validate_text(value, field, maximum=maximum)
    if any(ord(char) < 32 for char in text):
        raise ValueError(f"{field} contains unsupported control characters.")
    return text


class GuardrailService:
    """Single policy surface used by the agent and application boundaries.

    This service validates and authorizes operations. It does not authenticate
    principals; trusted host code must provide the principal value.
    """

    def __init__(
        self,
        *,
        max_iterations: int = MAX_ITERATIONS,
        max_tool_calls: int = MAX_TOOL_CALLS,
    ):
        if isinstance(max_iterations, bool) or not isinstance(max_iterations, int):
            raise ValueError("max_iterations must be an integer.")
        if not 1 <= max_iterations <= MAX_ITERATIONS:
            raise ValueError(f"max_iterations must be between 1 and {MAX_ITERATIONS}.")
        if isinstance(max_tool_calls, bool) or not isinstance(max_tool_calls, int):
            raise ValueError("max_tool_calls must be an integer.")
        if not 0 <= max_tool_calls <= MAX_TOOL_CALLS:
            raise ValueError(f"max_tool_calls must be between 0 and {MAX_TOOL_CALLS}.")
        self.max_iterations = max_iterations
        self.max_tool_calls = max_tool_calls

    @staticmethod
    def validate_user_input(value: Any) -> str:
        return validate_user_input(value)

    @staticmethod
    def validate_planner_output(value: Any) -> dict[str, Any]:
        return validate_decision(value)

    @staticmethod
    def validate_model_answer(value: Any) -> str:
        return validate_model_answer(value)

    @staticmethod
    def allowed_tools(principal: str = "agent") -> frozenset[str]:
        if not isinstance(principal, str) or principal not in TOOL_ROLES:
            raise PermissionError(f"Unknown tool principal '{principal}'.")
        return frozenset(TOOL_ROLES[principal])

    @staticmethod
    def validate_single_line(value: Any, field: str, maximum: int) -> str:
        return _validate_single_line(value, field, maximum)

    def authorize_tool(self, tool_name: str, principal: str = "agent") -> None:
        allowed = self.allowed_tools(principal)
        if not isinstance(tool_name, str) or tool_name not in ALL_TOOLS:
            raise ValueError(f"Unknown tool '{tool_name}'.")
        if tool_name not in allowed:
            raise PermissionError(
                f"Principal '{principal}' is not authorized for tool '{tool_name}'."
            )

    @staticmethod
    def validate_tool_arguments(
        tool_name: str, args: dict[str, Any]
    ) -> None:
        schemas = {
            "get_inventory_snapshot": ({"item_code"}, set()),
            "get_reorder_candidates": ({"item_code"}, set()),
            "compare_supplier_quotes": ({"item_code"}, {"item_code"}),
            "retrieve_context": ({"question"}, {"question"}),
            "create_draft_requisition": (
                {"item_code", "quantity", "supplier_name", "notes", "draft_id"},
                {"item_code", "quantity", "supplier_name"},
            ),
        }
        if tool_name not in schemas:
            raise ValueError(f"Unknown tool '{tool_name}'.")
        if not isinstance(args, dict) or any(not isinstance(key, str) for key in args):
            raise ValueError("Tool arguments must be an object with string keys.")
        allowed, required = schemas[tool_name]
        missing = required - args.keys()
        unknown = args.keys() - allowed
        if missing:
            raise ValueError(
                f"Missing required tool arguments: {', '.join(sorted(missing))}."
            )
        if unknown:
            raise ValueError(
                f"Unsupported tool arguments: {', '.join(sorted(unknown))}."
            )

        if "item_code" in args and args["item_code"] is not None:
            _validate_single_line(args["item_code"], "item_code", maximum=64)
        if tool_name != "create_draft_requisition":
            return

        quantity = args["quantity"]
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ValueError("quantity must be an integer.")
        if quantity <= 0:
            raise ValueError("quantity must be greater than zero.")
        if quantity > MAX_DRAFT_QUANTITY:
            raise ValueError(f"quantity must not exceed {MAX_DRAFT_QUANTITY}.")
        _validate_single_line(args["supplier_name"], "supplier_name", maximum=120)
        if "notes" in args:
            validate_text(args["notes"], "notes", maximum=1_000, allow_empty=True)
        if "draft_id" in args:
            draft_id = validate_text(args["draft_id"], "draft_id", maximum=64)
            if not re.fullmatch(r"[A-Za-z0-9_-]+", draft_id):
                raise ValueError("draft_id may contain only letters, numbers, '_' and '-'.")

    @staticmethod
    def validate_tool_result(tool_name: str, result: Any) -> None:
        try:
            encoded = json.dumps(result, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{tool_name} returned a non-JSON result.") from exc
        if len(encoded) > MAX_TOOL_RESULT_LENGTH:
            raise ValueError(f"{tool_name} returned an oversized result.")
        if not isinstance(result, dict):
            raise ValueError(f"{tool_name} returned an invalid result.")

        if tool_name in {"get_inventory_snapshot", "get_reorder_candidates"}:
            if not isinstance(result.get("items"), list):
                raise ValueError(f"{tool_name} result must contain an items list.")
            if len(result["items"]) > 5_000:
                raise ValueError(f"{tool_name} returned too many items.")
            if not isinstance(result.get("data_available"), bool):
                raise ValueError(f"{tool_name} result must identify data availability.")
            for field in ("inventory_item_count", "matched_item_count"):
                count = result.get(field)
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise ValueError(f"{tool_name} result has an invalid {field}.")
            for item in result["items"]:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("item_code"), str)
                    or not isinstance(item.get("status"), str)
                ):
                    raise ValueError(f"{tool_name} returned an invalid item.")
        elif tool_name == "compare_supplier_quotes":
            quotes = result.get("quotes")
            if not isinstance(quotes, list) or len(quotes) > 5_000:
                raise ValueError("compare_supplier_quotes returned an invalid quotes list.")
            if not isinstance(result.get("recommendation"), (str, dict)):
                raise ValueError("compare_supplier_quotes returned an invalid recommendation.")
            for quote in quotes:
                if not isinstance(quote, dict) or not isinstance(quote.get("supplier"), str):
                    raise ValueError("compare_supplier_quotes returned an invalid quote.")
        elif tool_name == "create_draft_requisition":
            if result.get("status") != "pending_human_approval":
                raise ValueError("Draft requisition must remain pending human approval.")
            if not isinstance(result.get("record"), dict):
                raise ValueError("Draft requisition result must contain its record.")
            if result["record"].get("status") != "pending_human_approval":
                raise ValueError("Draft requisition record must remain pending human approval.")

    @staticmethod
    def validate_retrieved_documents(documents: Any) -> list[dict[str, Any]]:
        if not isinstance(documents, list) or len(documents) > MAX_RETRIEVED_DOCUMENTS:
            raise ValueError("Retrieved evidence must be a bounded list.")
        for document in documents:
            if not isinstance(document, dict):
                raise ValueError("Retrieved evidence contains an invalid record.")
            if (
                not isinstance(document.get("text"), str)
                or len(document["text"]) > MAX_RETRIEVED_TEXT_LENGTH
                or not isinstance(document.get("source"), str)
                or len(document["source"]) > 500
            ):
                raise ValueError("Retrieved evidence is invalid or oversized.")
        if len(json.dumps(documents, allow_nan=False, ensure_ascii=False)) > MAX_AGENT_PROMPT_LENGTH:
            raise ValueError("Retrieved evidence exceeds the prompt size limit.")
        return documents

    @staticmethod
    def validate_retrieval_limit(top_k: Any) -> int:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_RETRIEVED_DOCUMENTS:
            raise ValueError(
                f"top_k must be an integer between 1 and {MAX_RETRIEVED_DOCUMENTS}."
            )
        return top_k

    @staticmethod
    def validate_prompt_payload(payload: str) -> str:
        if not isinstance(payload, str) or len(payload) > MAX_AGENT_PROMPT_LENGTH:
            raise ValueError("Question and retrieved evidence exceed the prompt size limit.")
        return payload

    def validate_agent_context(self, prompt: str, iteration: int, tool_calls: int) -> None:
        if len(prompt) > MAX_AGENT_PROMPT_LENGTH:
            raise ValueError("Planner context exceeded the runtime size limit.")
        if isinstance(iteration, bool) or not isinstance(iteration, int):
            raise ValueError("iteration must be an integer.")
        if iteration > self.max_iterations:
            raise ValueError("The maximum agent-iteration limit was reached.")
        if isinstance(tool_calls, bool) or not isinstance(tool_calls, int):
            raise ValueError("tool_calls must be an integer.")
        if tool_calls > self.max_tool_calls:
            raise ValueError("The maximum tool-call limit was reached.")

    @staticmethod
    def validate_completion(final_status: str, steps: list[dict[str, Any]]) -> None:
        if final_status == "COMPLETED_PENDING_HUMAN_REVIEW":
            has_pending_draft = any(
                step.get("action") == "create_draft_requisition"
                and isinstance(step.get("observation"), dict)
                and step["observation"].get("status") == "pending_human_approval"
                for step in steps
            )
            if not has_pending_draft:
                raise ValueError("Completion claimed without a pending draft.")
        elif final_status == "COMPLETED_NO_REORDER":
            verified_no_candidates = any(
                step.get("action") == "get_reorder_candidates"
                and isinstance(step.get("observation"), dict)
                and step["observation"].get("data_available") is True
                and step["observation"].get("inventory_item_count", 0) > 0
                and step["observation"].get("matched_item_count", 0) > 0
                and step["observation"].get("items") == []
                for step in steps
            )
            if not verified_no_candidates:
                raise ValueError(
                    "No-reorder completion requires an empty candidates result backed by available inventory."
                )
