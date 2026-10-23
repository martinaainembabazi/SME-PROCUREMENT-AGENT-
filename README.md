 SME Procurement-Preparation Agent for a supermarket

Course: BSE4104 Emerging Trends in Software Engineering 
8-Week AI-Native & Agentic Engineering Capstone
Makerere University, College of Computing and Information Sciences
GROUP D

## Problem
A supermarket needs help preparing procurement decisions. This project builds an AI-native agent that:

1. Reads sample inventory data.
2. Checks which items need reordering.
3. Compares supplier quotations.
4. Drafts a purchase requisition.
5. Routes the requisition for human approval before any purchasing action is taken.

AI is used for:reasoning over inventory/quotation data and drafting the requisition.
**Deterministic software remains responsible for:** reorder-threshold rules, requisition formatting/validation, and enforcing that no purchase is finalized without human sign-off.
**The agent may:** read inventory/quotation data, compare quotations, draft a requisition, create/route a requisition record.
**The agent may not:** place real orders, make payments, select/award a supplier, or commit CACv Supermarket to any purchase autonomously.
**Data used:** synthetic/team-created inventory and supplier quotation CSV/JSON files (no real Supermarket financial or supplier data).

## Repository Structure

```
README.md
docs/
  requirements/       # Project charter, user stories, acceptance criteria, AI Boundary Matrix
  architecture/        # Architecture & context diagrams
  weekly-reports/       # Weekly progress reports (1-2 pages each)
  evaluation/          # Evaluation sets, results, failure catalogue
prompts/               # Versioned prompt specifications
knowledge/             # Corpus metadata/provenance (no restricted data committed)
src/                   # Application source code
tests/                 # Automated tests
evidence/
  traces/              # Agent execution traces
  screenshots/         # Screenshots of the working system
  demo/                # Demo recordings/assets
.env.example           # Template for required environment variables (never commit real secrets)
```

## Status

Week 1 of 8 — problem framing, requirements and repository/task-board setup.

## AI Use Declaration

This project uses AI assistance (e.g. Claude) for design, coding, documentation and evaluation support. See `docs/ai-engineering-log.md` for a running log of material AI-assisted decisions.


## Week 2 base model implementation
## Setup

1. Clone the repo
2. Create and activate a virtual environment:
   - Windows: `python -m venv venv && venv\Scripts\activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and add your `GEMINI_API_KEY`
5. Build the knowledge index: `python src/ingest.py`
6. Run the baseline: `python src/baseline_demo.py`
7. Run the agent traces: `python tests/run_agent_traces.py`

## Web Application (Week 8 MVP)

Run from the project root (works whether or not the venv is activated):

```
.\venv\Scripts\python -m streamlit run src/app.py
```

With the venv activated (`.\venv\Scripts\Activate.ps1`), `streamlit run src/app.py` also works. The app opens at http://localhost:8501.

On first start the app asks you to create the **Business Owner** account. Further accounts are added under **Administration** (or `python src/auth.py create <username> <role> "<Full Name>"`).

| Role | Can do |
|---|---|
| Viewer | Read everything |
| Procurement Officer | Run the agent, manage inventory and quotes, create requisitions, record deliveries |
| Procurement Manager | Officer rights + approve/reject requisitions **below UGX 2,000,000**, manage supplier memory |
| Business Owner | Everything, including approvals at or above UGX 2,000,000, users and the knowledge index |

Features:
- **Dashboard** — stock below threshold, approvals waiting, deliveries due.
- **AI agent** — runs the bounded agent; it can read data and create *draft* requisitions only.
- **Requisitions** — full lifecycle: draft (agent or manual) → approve/reject → record delivery (updates stock) → CSV export. Approval enforces the policy: quote on file, payment terms present, MOQ met, owner sign-off at UGX 2,000,000+.
- **Inventory** and **Supplier quotes** — add, edit and remove records; the agent's tools read the same files.
- **Knowledge assistant** — grounded answers with sources.
- **Supplier memory** — approved supplier choices and audit log.
- **Agent run history** — every run with its step trace.
- **Administration** — users, roles, knowledge-index rebuild.

Service modules: `src/auth.py`, `src/data_store.py`, `src/requisitions.py`. Tests: `tests/test_mvp_services.py`. Accounts are stored as bcrypt hashes in `data/users.json` (git-ignored).

Approval is a human action in the app. It is never exposed to the model as a tool.

## Model Integration
- Model: Gemini (configured via `MODEL_NAME` in `.env`, default `gemini-3.6-flash`)
- Client: `src/model_client.py`
- Prompts: versioned in `prompts/sme_procurement/` via `manifest.json`
- Prompt loader: `src/prompt_loader.py`

