# AI Boundary Matrix - SME Procurement Agent

| Capability / Task | AI Responsibility | Deterministic System Responsibility | Human-in-the-Loop Approval Required? |
| :--- | :--- | :--- | :--- |
| **Inventory Threshold Monitoring** | Summarize low-stock items into plain-text alerts. | Query database and flag items where Stock <= Threshold. | **No** (Read-only view) |
| **Supplier Quote Parsing** | Extract prices, lead times, and terms from JSON/CSV. | Validate JSON schema and check for missing fields. | **No** (Read-only processing) |
| **Quotation Comparison** | Format supplier options into an organized table. | Compute total costs (Unit Price * Quantity). | **No** (Decision-support) |
| **Draft Requisition Creation** | Draft requisition notes for selected items. | Generate unique IDs and save in PENDING status. | **Yes** (Officer must confirm) |
| **Order Authorization** | *Prohibited* (Cannot make financial commitments). | Block autonomous purchase execution. | **Yes** (Strict human sign-off) |
