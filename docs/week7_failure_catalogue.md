Bug 1 (Guardrail): retrieve_context was missing from the allow-list, causing a hard crash. Fixed by adding it to guardrail_service.py.

Bug 2 (Parsing): Gemini sometimes wrapped JSON in markdown backticks, causing a parse error. Fixed by adding slicing logic to security.py.

Bug 3 (API Resilience): Gemini 503/429 errors caused the CLI to crash with a Python traceback. Fixed by catching RuntimeError in agent.py and returning a safe BLOCKED_TOOL_FAILURE.