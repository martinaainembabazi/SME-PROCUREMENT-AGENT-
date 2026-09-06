# Week 1 Progress Report: SME Procurement-Preparation Agent

**Course:** BSE4104 Emerging Trends in Software Engineering  
**Group Size:** 5 Members  
**Week Ending:** September 4, 2026  

---

### 1. Weekly Objectives & Progress Summary
During Week 1, our team focused on problem framing, requirement engineering, boundary definition, and establishing the development environment for the SME Procurement-Preparation Agent.

* **Status:** All Week 1 requirements completed on schedule.
* **Key Achievements:**
  * Selected Recommendation 2 (SME Procurement-Preparation Agent) from Section 3 of the brief.
  * Formulated the Minimum Proposal Statement, 3 core user stories, and acceptance criteria.
  * Designed the AI Boundary Matrix establishing deterministic limits and Human-in-the-Loop approval gates.
  * Set up the official GitHub repository structure, `.env.example`, and directory hierarchy.
  * Configured the ClickUp workspace and assigned individual Week 1 tasks.
  * Created synthetic datasets (`inventory.csv` and `supplier_quotes.json`) for early model grounding.

---

### 2. Key Engineering Decisions & Rationale
* **Selected Scope:** Focused strictly on low-stock detection, quote comparison, and draft requisition generation to ensure a bounded 8-week engineering effort.
* **Deterministic Math Boundary:** All numerical calculations (e.g., Total Cost = Unit Price * Quantity) will be performed by deterministic application logic rather than foundation model generation to eliminate financial hallucination risks.
* **Human-in-the-Loop Gate:** Enforced an explicit approval boundary before any draft purchase requisition record is saved or finalized.

---

### 3. Challenges & Mitigation Strategy
* **Challenge:** Risk of the LLM fabricating missing pricing data or inventing unapproved supplier names during quote extraction.
* **Mitigation Strategy:** Drafted System Prompt v0.1 with strict grounding rules that restrict responses strictly to provided JSON/CSV contexts. In Week 2, we will add schema validation tests.

---

### 4. Individual Member Contribution Summary

| Member Name | Assigned Role | Weekly Ownership & Accomplishments | Evidence Link |
| :--- | :--- | :--- | :--- |
| **Member 1** | Project / Requirements Lead | Drafted the Project Charter (problem definition, user context, AI value, scope constraints). | `docs/requirements/charter.md` |
| **Member 2** | AI Engineering Lead | Created System Prompt v0.1, user stories, and synthetic datasets. | `prompts/v0.1_system_prompt.md`, `knowledge/` |
| **Member 3** | Application / Integration Lead | Designed initial architecture and context diagrams. | `docs/architecture/` |
| **Member 4** | DevOps / Documentation Lead | Created GitHub repo structure, `.env.example`, and README.md setup. | `README.md` |
| **Martina Ainembabazi** | Quality & Security Lead | Created AI Boundary Matrix, managed ClickUp board, and compiled Week 1 Progress Report. | `docs/requirements/ai_boundary_matrix.md`, `docs/weekly-reports/week-01-report.md` |

---

### 5. Plan for Week 2 (Foundation-Model Engineering & Prompting)
* Select an accessible foundation model (evaluating cost, latency, context limits, and privacy).
* Integrate model API into the application codebase (`src/`).
* Create Prompt Specification v1.0 detailing role, constraints, formatting, and failure behavior.
* Develop 10 initial prompt evaluation test cases to benchmark expected vs. actual outputs.
