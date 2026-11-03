"""
Retrieve relevant procurement knowledge from ChromaDB.

This module:
1. Embeds the user's question using Gemini.
2. Searches the ChromaDB vector store.
3. Returns the most relevant chunks and their sources.
"""

import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from google import genai


load_dotenv()


# --------------------------------------------------
# Configuration
# --------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

CHROMA_DIR = ROOT / "evidence" / "chroma"

COLLECTION_NAME = "sme_procurement"

EMBED_MODEL = "gemini-embedding-001"


# --------------------------------------------------
# Clients
# --------------------------------------------------

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError(
        "GEMINI_API_KEY is missing from the .env file."
    )


client = genai.Client(api_key=api_key)

chroma = chromadb.PersistentClient(
    path=str(CHROMA_DIR)
)


# --------------------------------------------------
# Retriever
# --------------------------------------------------

class Retriever:

    def __init__(self):

        self.collection = chroma.get_collection(
            name=COLLECTION_NAME
        )

    def embed_query(self, question: str):

        response = client.models.embed_content(
            model=EMBED_MODEL,
            contents=[question]
        )

        return response.embeddings[0].values

    def retrieve(
        self,
        question: str,
        top_k: int = 5
    ):

        query_embedding = self.embed_query(
            question
        )

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )

        retrieved = []

        documents = results.get("documents", [[]])[0]

        metadatas = results.get("metadatas", [[]])[0]

        distances = results.get("distances", [[]])[0]

        for i, document in enumerate(documents):

            metadata = (
                metadatas[i]
                if i < len(metadatas)
                else {}
            )

            distance = (
                distances[i]
                if i < len(distances)
                else None
            )

            retrieved.append({
                "text": document,
                "source": metadata.get(
                    "source",
                    "unknown"
                ),
                "chunk": metadata.get(
                    "chunk",
                    i
                ),
                "distance": distance
            })

        return retrieved


# --------------------------------------------------
# Test
# --------------------------------------------------

if __name__ == "__main__":

    retriever = Retriever()

    question = input(
        "Enter a procurement question: "
    )

    results = retriever.retrieve(
        question,
        top_k=5
    )

    print("\n" + "=" * 60)
    print("RETRIEVED EVIDENCE")
    print("=" * 60)

    for i, result in enumerate(
        results,
        start=1
    ):

        print(
            f"\n[{i}] Source: {result['source']}"
        )

        print(
            f"Chunk: {result['chunk']}"
        )

        print(
            f"Distance: {result['distance']}"
        )

        print(
            f"Text:\n{result['text']}"
        )