"""
Build grounded context from retrieved procurement evidence.
"""


def build_context(retrieved_documents):

    if not retrieved_documents:

        return (
            "NO EVIDENCE WAS RETRIEVED FROM THE "
            "PROCUREMENT KNOWLEDGE CORPUS."
        )

    sections = []

    for i, document in enumerate(
        retrieved_documents,
        start=1
    ):

        source = document.get(
            "source",
            "unknown"
        )

        chunk = document.get(
            "chunk",
            "unknown"
        )

        text = document.get(
            "text",
            ""
        )

        sections.append(
            f"""
SOURCE {i}
Source file: {source}
Chunk: {chunk}

Evidence:
{text}
""".strip()
        )

    return "\n\n".join(sections)