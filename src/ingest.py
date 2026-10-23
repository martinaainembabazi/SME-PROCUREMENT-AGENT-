"""
Ingest the SME procurement knowledge corpus into a ChromaDB vector store.
Handles .md, .txt, .csv, and .json files.

Run: python src/ingest.py
"""
import csv
import json
import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from google import genai

load_dotenv()

# ---- Config ----
ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"
CHROMA_DIR = ROOT / "evidence" / "chroma"
COLLECTION_NAME = "sme_procurement"
EMBED_MODEL = "gemini-embedding-001"
CHUNK_SIZE = 400       # words per chunk (text)
CHUNK_OVERLAP = 50     # word overlap between chunks

# ---- Clients ----
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using Gemini embeddings."""
    response = client.models.embed_content(
        model=EMBED_MODEL,
        contents=texts,
    )
    return [e.values for e in response.embeddings]


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    words = text.split()
    if not words:
        return []
    chunks = []
    step = max(1, size - overlap)
    for i in range(0, len(words), step):
        chunk = " ".join(words[i:i + size]).strip()
        if chunk:
            chunks.append(chunk)
        if i + size >= len(words):
            break
    return chunks


def csv_to_chunks(path: Path):
    """One chunk per row, with column headers prepended for context."""
    chunks = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parts = [f"{k}: {v}" for k, v in row.items() if v not in (None, "")]
            chunks.append(f"[{path.stem}] " + " | ".join(parts))
    return chunks


def json_to_chunks(path: Path):
    """Flatten JSON to readable text. One chunk per top-level entry."""
    data = json.loads(path.read_text(encoding="utf-8"))
    chunks = []

    def flatten(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                flatten(v, f"{prefix}{k}.")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                flatten(v, f"{prefix}[{i}].")
        else:
            chunks.append(f"{prefix.rstrip('.')}: {obj}")

    flatten(data)
    # Group into ~CHUNK_SIZE-word chunks
    grouped, buf = [], []
    buf_len = 0
    for line in chunks:
        buf.append(line)
        buf_len += len(line.split())
        if buf_len >= CHUNK_SIZE:
            grouped.append("\n".join(buf))
            buf, buf_len = [], 0
    if buf:
        grouped.append("\n".join(buf))
    return grouped


def text_to_chunks(path: Path):
    return chunk_text(path.read_text(encoding="utf-8", errors="ignore"))


def extract_chunks(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return csv_to_chunks(path)
    if suffix == ".json":
        return json_to_chunks(path)
    if suffix in (".md", ".txt"):
        return text_to_chunks(path)
    return []


def ingest(reset: bool = True):
    # Fresh collection each run
    try:
        if reset:
            chroma.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = chroma.get_or_create_collection(COLLECTION_NAME)

    total_chunks = 0
    files_processed = 0

    for path in sorted(KNOWLEDGE_DIR.rglob("*")):
        if not path.is_file():
            continue
        chunks = extract_chunks(path)
        if not chunks:
            print(f"[skip] {path.relative_to(KNOWLEDGE_DIR)} — no chunks")
            continue

        rel = str(path.relative_to(KNOWLEDGE_DIR))
        ids = [f"{rel}::{i}" for i in range(len(chunks))]
        metadatas = [{"source": rel, "chunk": i} for i in range(len(chunks))]

        # Batch embeddings to avoid API limits
        batch_size = 20
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start:start + batch_size]
            try:
                embeddings = embed(batch)
            except Exception as e:
                print(f"[ERROR] embedding {rel} batch {start}: {e}")
                continue
            collection.add(
                ids=ids[start:start + len(batch)],
                embeddings=embeddings,
                documents=batch,
                metadatas=metadatas[start:start + len(batch)],
            )

        files_processed += 1
        total_chunks += len(chunks)
        print(f"[ok]   {rel} — {len(chunks)} chunks")

    print(f"\nIngested {files_processed} files, {total_chunks} chunks.")
    print(f"Vector store: {CHROMA_DIR}")
    print(f"Collection:  {COLLECTION_NAME}")


if __name__ == "__main__":
    ingest()