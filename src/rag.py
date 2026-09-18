"""
Working RAG pipeline for the SME Procurement Preparation Agent.

Pipeline:

Question
   ↓
Retriever
   ↓
Relevant ChromaDB evidence
   ↓
Context builder
   ↓
Gemini
   ↓
Grounded answer + source references
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from retriever import Retriever
from context_builder import build_context


load_dotenv()


# --------------------------------------------------
# Configuration
# --------------------------------------------------

MODEL_NAME = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)


# --------------------------------------------------
# RAG Pipeline
# --------------------------------------------------

class RAGPipeline:

    def __init__(self):

        api_key = os.getenv(
            "GEMINI_API_KEY"
        )

        if not api_key:

            raise ValueError(
                "GEMINI_API_KEY is missing "
                "from the .env file."
            )

        self.client = genai.Client(
            api_key=api_key
        )

        self.retriever = Retriever()


    def generate_answer(
        self,
        question: str,
        top_k: int = 5
    ):

        # ------------------------------------------
        # 1. Retrieve evidence
        # ------------------------------------------

        retrieved = self.retriever.retrieve(
            question,
            top_k=top_k
        )


        # ------------------------------------------
        # 2. Build context
        # ------------------------------------------

        context = build_context(
            retrieved
        )


        # ------------------------------------------
        # 3. Grounded prompt
        # ------------------------------------------

        prompt = f"""
You are the SME Procurement Preparation Agent.

Your task is to answer procurement-preparation
questions using ONLY the evidence retrieved from
the controlled knowledge corpus.

========================
GROUNDING RULES
========================

1. Use only information contained in the
   retrieved evidence.

2. Do not invent facts, prices, quantities,
   suppliers, lead times, payment terms,
   MOQs or other procurement information.

3. If the retrieved evidence does not contain
   enough information to answer the question,
   explicitly state that the available evidence
   is insufficient.

4. Do not use general knowledge to fill missing
   procurement information.

5. Distinguish clearly between information found
   in the evidence and any calculation made from
   that evidence.

6. Never claim that a purchase has been finalized.

7. Never claim that an order has been placed.

8. Never claim that payment has been made.

9. The agent prepares information for human review.

10. When drafting a purchase requisition, end with:

Pending human approval.

========================
RETRIEVED EVIDENCE
========================

{context}

========================
USER QUESTION
========================

{question}

========================
RESPONSE
========================

Provide a concise answer based strictly
on the retrieved evidence.
"""


        # ------------------------------------------
        # 4. Generate grounded answer
        # ------------------------------------------

        response = self.client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )


        answer = response.text


        # ------------------------------------------
        # 5. Return answer + evidence
        # ------------------------------------------

        return {
            "question": question,
            "answer": answer,
            "sources": retrieved
        }