import json

notebook_content = {
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# CACv Procurement Agent — RAG Evaluation Pipeline\n",
    "This notebook fully reproduces the 15-case evaluation using ChromaDB (`sme_procurement`), `gemini-3.6-flash`, and exponential backoff retry logic."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "!pip install google-generativeai chromadb pandas -q"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "import os\n",
    "import time\n",
    "import csv\n",
    "import pandas as pd\n",
    "import chromadb\n",
    "import google.generativeai as genai\n",
    "from google.colab import userdata\n",
    "\n",
    "# Configure Gemini API Key\n",
    "genai.configure(api_key=userdata.get('GEMINI_API_KEY'))"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "# 1. Ingest Policy Documents into ChromaDB\n",
    "docs = {\n",
    "    \"supplier_selection_criteria.md\": \"\"\"# Supplier Selection Criteria\n",
    "When multiple suppliers offer the same item, compare on:\n",
    "| Criterion | Weight | Notes |\n",
    "| Price per unit | 40% | Lower is better |\n",
    "| Lead time | 25% | Shorter is better, especially for high-criticality items |\n",
    "| MOQ flexibility | 15% | Lower MOQ preferred |\n",
    "| Payment terms | 10% | Longer terms preferred |\n",
    "| Reliability | 10% | Internal history |\n",
    "**Rule:** Do not select on price alone. A slightly higher price with much shorter lead time may be preferable for high-criticality items like cement and iron sheets.\"\"\",\n",
    "\n",
    "    \"approval_workflow.md\": \"\"\"# Approval Workflow\n",
    "1. Agent prepares Draft Purchase Requisition.\n",
    "2. Requisition routed to Procurement Manager.\n",
    "3. Total cost < UGX 2,000,000: Procurement Manager approves directly.\n",
    "4. Total cost ≥ UGX 2,000,000: Escalated to Business Owner.\n",
    "5. Finance team performs payment execution — agent has no payment permissions.\n",
    "Stop Conditions:\n",
    "- Missing supplier payment terms → halt and request.\n",
    "- MOQ below supplier minimum → halt and suggest alternative.\n",
    "- Total exceeds owner threshold → escalate.\"\"\",\n",
    "\n",
    "    \"reorder_policy.md\": \"\"\"# SME Reorder Policy\n",
    "1. Reorder Trigger: current_qty falls below reorder_threshold.\n",
    "2. Priority Rules: High criticality items reordered first. Items with lead_time_days > 14 ordered before threshold if weekly sales > 20% stock.\n",
    "3. Order Quantity: Reach max_stock where defined, otherwise 2 × reorder_threshold.\n",
    "4. Approval: Orders above UGX 2,000,000 require owner approval.\"\"\"\n",
    "}\n",
    "\n",
    "client = chromadb.PersistentClient(path=\"/content/evidence/chroma\")\n",
    "try:\n",
    "    client.delete_collection(\"sme_procurement\")\n",
    "except:\n",
    "    pass\n",
    "\n",
    "collection = client.create_collection(\"sme_procurement\")\n",
    "for fname, content in docs.items():\n",
    "    collection.add(documents=[content], ids=[fname], metadatas=[{\"source\": fname}])\n",
    "\n",
    "print(f\"Ingested {collection.count()} document files into 'sme_procurement'.\")"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "# 2. RAG Pipeline Class with Exponential Backoff\n",
    "class RAGPipeline:\n",
    "    def __init__(self):\n",
    "        self.model = genai.GenerativeModel(\"gemini-3.6-flash\")\n",
    "        self.client = chromadb.PersistentClient(path=\"/content/evidence/chroma\")\n",
    "        self.collection = self.client.get_collection(\"sme_procurement\")\n",
    "\n",
    "    def retrieve_context(self, query, top_k=3):\n",
    "        results = self.collection.query(query_texts=[query], n_results=top_k)\n",
    "        docs = results.get(\"documents\", [[]])[0]\n",
    "        return docs if docs else [\"No context found.\"]\n",
    "\n",
    "    def generate_answer(self, query, top_k=3):\n",
    "        sources = self.retrieve_context(query, top_k=top_k)\n",
    "        context_str = \"\\n\\n---\\n\\n\".join(sources)\n",
    "        prompt = f\"\"\"Answer strictly using only the provided context. If information is missing, state that it is not covered.\n",
    "\n",
    "Context:\n",
    "{context_str}\n",
    "\n",
    "Question: {query}\n",
    "Answer:\"\"\"\n",
    "        for attempt in range(5):\n",
    "            try:\n",
    "                resp = self.model.generate_content(prompt)\n",
    "                return {\"answer\": resp.text, \"sources\": sources}\n",
    "            except Exception as e:\n",
    "                time.sleep(5.0 * (2 ** attempt))\n",
    "        raise RuntimeError(\"Max retries exceeded.\")"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "# 3. Execute 15 Test Cases\n",
    "pipeline = RAGPipeline()\n",
    "test_cases = [\n",
    "    {\"id\": 1, \"q\": \"What total cost threshold requires Business Owner approval?\"},\n",
    "    {\"id\": 2, \"q\": \"What is the approval threshold for the Procurement Manager?\"},\n",
    "    {\"id\": 3, \"q\": \"Can the agent perform payment execution?\"},\n",
    "    {\"id\": 4, \"q\": \"What are the priority rules for high criticality items?\"},\n",
    "    {\"id\": 5, \"q\": \"What criteria are used to select a supplier when multiple offer the same item?\"},\n",
    "    {\"id\": 6, \"q\": \"When must an item be reordered?\"},\n",
    "    {\"id\": 7, \"q\": \"What is the weight given to price per unit in supplier selection?\"},\n",
    "    {\"id\": 8, \"q\": \"What happens if a supplier's MOQ is missing or not met?\"},\n",
    "    {\"id\": 9, \"q\": \"Who performs payment execution?\"},\n",
    "    {\"id\": 10, \"q\": \"How is order quantity calculated for standard reorders?\"},\n",
    "    {\"id\": 11, \"q\": \"What is the penalty for vendor late delivery of hardware?\"},\n",
    "    {\"id\": 12, \"q\": \"What is the policy for vendor invoice settlement timelines?\"},\n",
    "    {\"id\": 13, \"q\": \"Can travel expenses be reimbursed without prior manager sign-off?\"},\n",
    "    {\"id\": 14, \"q\": \"Who must sign off on hardware disposal forms?\"},\n",
    "    {\"id\": 15, \"q\": \"What is the rule regarding high-criticality items like cement and iron sheets?\"}\n",
    "]\n",
    "\n",
    "results = []\n",
    "for c in test_cases:\n",
    "    print(f\"Evaluating Case {c['id']}...\")\n",
    "    res = pipeline.generate_answer(c['q'])\n",
    "    results.append({\"case_id\": c['id'], \"question\": c['q'], \"generated_answer\": res['answer']})\n",
    "    time.sleep(6.0)\n",
    "\n",
    "df = pd.DataFrame(results)\n",
    "df.to_csv(\"rag_evaluation_15_cases.csv\", index=False)\n",
    "print(\"Execution complete. Results saved to rag_evaluation_15_cases.csv!\")"
   ]
  }
 ],
 "metadata": {
  "language_info": {"name": "python"},
  "orig_nbformat": 4
 },
 "nbformat": 4,
 "nbformat_minor": 2
}

with open("rag_evaluation_pipeline.ipynb", "w", encoding="utf-8") as f:
    json.dump(notebook_content, f, indent=2)

print("Notebook 'rag_evaluation_pipeline.ipynb' successfully created!")