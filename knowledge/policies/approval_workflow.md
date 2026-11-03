# Approval Workflow (Team-Created, Synthetic)

## Steps
1. Agent prepares a **Draft Purchase Requisition** with items, quantities, chosen supplier, and total cost.
2. Requisition is routed to the **Procurement Manager** for review.
3. If total cost **< UGX 2,000,000**, Procurement Manager may approve directly.
4. If total cost **≥ UGX 2,000,000**, requisition is escalated to the **Business Owner**.
5. Approved requisitions are converted to a Purchase Order (outside this agent's scope).
6. Any payment execution is performed by the finance team — the agent has **no payment permissions**.

## Stop Conditions
- Missing supplier payment terms → halt and request.
- MOQ below supplier minimum → halt and suggest alternative.
- Total exceeds owner threshold → escalate.