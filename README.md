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
5. Run the baseline: `python src/baseline_demo.py`
6. Run the evaluation: `python tests/run_eval.py`

## Model Integration
- Model: Gemini (configured via `MODEL_NAME` in `.env`, default `gemini-3.6-flash`)
- Client: `src/model_client.py`
- Prompts: versioned in `prompts/sme_procurement/` via `manifest.json`
- Prompt loader: `src/prompt_loader.py`

