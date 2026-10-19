# Week 7: Failure Catalogue

## 1. Purpose

This document records failures and potential failure cases identified during the evaluation of the SME Procurement Preparation Agent. It describes the expected behaviour, possible causes, corrective actions, and retesting evidence required to determine whether each issue has been resolved.

The agent supports procurement preparation by retrieving evidence, comparing supplier quotations, identifying items for reorder, and preparing requisition drafts. It must not approve requisitions, place orders, or make payments without the required authorization.

## 2. Failure Catalogue

### FC-01: Model API Service Failure

**Related scenario:** E23 and E25

**Failure description:** The Gemini API returned a `503 UNAVAILABLE` error during previous testing. This prevented the model from completing the requested operation.

**Expected behaviour:** The agent should handle temporary service failures gracefully, apply bounded retries where appropriate, and inform the user if the operation cannot be completed.

**Observed behaviour:** A `503 UNAVAILABLE` error was encountered during an earlier run. The effectiveness of the current error-handling logic has not yet been confirmed.

**Possible cause:** Temporary API service unavailability or high service demand.

**Remediation:** Implement bounded retries with a delay between attempts. If the service remains unavailable, return a clear error message and avoid presenting an incomplete result as successful.

**Retest evidence:** Record the test date, number of retry attempts, final output, and whether the agent failed safely. Do not mark this failure as resolved until the retest is completed.

**Status:** Observed; remediation and retesting require confirmation.

### FC-02: Unsupported Inventory Claims

**Related scenarios:** E02, E11, E12 and E15

**Failure description:** The agent may provide an incorrect stock quantity or reorder recommendation if it relies on an unsupported user claim or lacks the required inventory evidence.

**Expected behaviour:** Inventory-related answers must be grounded in the available inventory records and reorder thresholds. Missing evidence must be disclosed.

**Possible cause:** Incomplete retrieval, incorrect source selection, or failure to distinguish user-provided claims from verified records.

**Remediation:** Retrieve the relevant inventory record and threshold before making a recommendation. Clearly state when the necessary information is unavailable.

**Retest evidence:** Run the relevant scenarios and record the retrieved evidence, generated answer, and whether the answer agrees with the source records.

**Status:** Requires testing to establish whether the failure occurs.

### FC-03: Fabricated Supplier Comparison

**Related scenarios:** E03, E10, E13, E14 and E22

**Failure description:** The agent may compare suppliers or claim that one supplier has the lowest price or shortest lead time without sufficient quotation evidence.

**Expected behaviour:** Supplier comparisons must use available quotations and their documented prices, lead times, and other relevant details. Missing quotations or comparison fields must be disclosed.

**Possible cause:** Incomplete quotation retrieval or the model generating details that are not supported by the evidence.

**Remediation:** Retrieve the relevant quotations before comparing suppliers. Identify missing information and avoid inventing prices, suppliers, or delivery times.

**Retest evidence:** Record the quotation sources retrieved, the comparison produced, and whether each claim is supported by the source documents.

**Status:** Requires testing to establish whether the failure occurs.

### FC-04: Unsafe Requisition Approval

**Related scenarios:** E18, E26, E28, E29 and E30

**Failure description:** The agent may attempt to approve a requisition, place a purchase order, or bypass human approval when asked to do so.

**Expected behaviour:** The agent may prepare a requisition draft but must preserve its pending-approval status. Approval and order placement must remain outside its permitted actions.

**Possible cause:** Missing authorization checks, unclear workflow boundaries, or instructions that conflict with the agent's permitted role.

**Remediation:** Enforce authorization checks before sensitive actions. Restrict the agent to the configured tool allow-list and require the appropriate human approval for actions outside its permitted scope.

**Retest evidence:** Run the unauthorized-action scenarios and record whether the agent refuses the action or safely hands it over. Confirm that no approval or order-placement action occurs.

**Status:** Requires testing to establish whether the failure occurs.

### FC-05: Invalid Requisition Input

**Related scenarios:** E08 and E09

**Failure description:** The agent may accept a requisition with a zero quantity or proceed without a required item code.

**Expected behaviour:** Invalid quantities and missing required fields must be rejected or clarified before a draft is created.

**Possible cause:** Missing input validation or incomplete validation rules.

**Remediation:** Validate required fields, data types, and allowed values before passing inputs to procurement tools. Return a clear message identifying what needs to be corrected.

**Retest evidence:** Submit invalid quantities and missing item codes. Record whether each request is rejected or clarified and whether an invalid draft is prevented.

**Status:** Requires testing to establish whether the failure occurs.

### FC-06: Prompt Injection Through Untrusted Content

**Related scenarios:** E16, E17 and E19

**Failure description:** Instructions contained in supplier documents or user messages may attempt to override procurement policies, reveal hidden instructions, or manipulate supplier information.

**Expected behaviour:** The agent must treat retrieved documents as evidence rather than authoritative instructions. It must follow its configured rules and use verified procurement data.

**Possible cause:** Failure to separate trusted instructions from untrusted user input or retrieved content.

**Remediation:** Clearly separate system instructions from retrieved evidence, validate tool requests, and prevent untrusted content from overriding authorization rules or procurement policies.

**Retest evidence:** Submit the adversarial scenarios and record whether the agent follows its permitted role, protects hidden instructions, and avoids unsupported changes to procurement data.

**Status:** Requires testing to establish whether the failure occurs.

### FC-07: Retrieval or Tool Failure

**Related scenarios:** E21, E22 and E24

**Failure description:** An inventory, quotation, or draft-storage operation may fail or return incomplete information, preventing the agent from completing a task.

**Expected behaviour:** The agent should report the failure clearly, avoid inventing missing evidence, and never claim that a draft was saved when storage failed.

**Possible cause:** An unavailable data source, missing file, tool exception, or unsuccessful storage operation.

**Remediation:** Add error handling around tool calls, validate returned data, and distinguish successful operations from failed or incomplete ones.

**Retest evidence:** Simulate or reproduce the relevant failure where possible. Record the tool result, error handling, final response, and whether the agent avoided claiming success incorrectly.

**Status:** Requires testing to establish whether the failure occurs.

## 3. Retesting and Evidence

Each failure must be tested using a reproducible scenario. The following information should be recorded for every confirmed failure:

- **Test ID:** The evaluation scenario used.
- **Initial result:** What the agent actually did before remediation.
- **Root cause:** The confirmed reason the failure occurred.
- **Corrective action:** The code or configuration change made.
- **Retest result:** What happened when the same scenario was run again.
- **Evidence:** Relevant console output, logs, traces, or screenshots.
- **Final status:** Open, fixed but not retested, or successfully retested.

A failure should only be marked as successfully resolved after the same scenario has been rerun and the expected behaviour has been demonstrated.

## 4. Summary

The failure catalogue covers model service errors, unsupported inventory claims, fabricated supplier comparisons, unauthorized procurement actions, invalid inputs, prompt injection, and retrieval or tool failures.

These categories identify important areas for evaluation, but they do not automatically demonstrate that every failure has occurred. The final catalogue must distinguish confirmed failures from potential failure cases and include actual before-and-after evidence for at least five genuine failures, as required by the Week 7 deliverables.
