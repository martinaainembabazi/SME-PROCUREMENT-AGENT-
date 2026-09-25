"""
Command-line interface for the SME Procurement
Preparation RAG system.
"""

from rag import RAGPipeline
from orchestration import AppToolOrchestrator
import os

MODEL_NAME = os.getenv(
    "GEMINI_MODEL",
    os.getenv("MODEL_NAME", "gemini-2.5-flash")
)

TOOL_EXAMPLES = "\n".join([
    "Tool commands:",
    "  inventory [item_code]   -> get_inventory_snapshot",
    "  draft <item_code> <qty> <supplier> [notes] -> create_draft_requisition",
    "  exit",
])


def display_sources(sources):

    print("\n" + "=" * 60)
    print("SOURCE GROUNDING")
    print("=" * 60)

    if not sources:

        print(
            "No evidence was retrieved."
        )

        return


    for number, source in enumerate(
        sources,
        start=1
    ):

        print(
            f"\n[{number}] {source['source']}"
        )

        print(
            f"    Chunk: {source['chunk']}"
        )

        if source["distance"] is not None:

            print(
                f"    Chroma distance: "
                f"{source['distance']:.4f}"
            )


def run_tool_command(command: str, orchestrator: AppToolOrchestrator):
    raw = command.strip()
    if not raw:
        return None

    if raw.lower() == "inventory":
        return orchestrator.get_inventory_snapshot()

    if raw.lower().startswith("inventory "):
        item_code = raw.split(None, 1)[1].strip()
        return orchestrator.get_inventory_snapshot(item_code=item_code)

    if raw.lower().startswith("draft "):
        parts = raw.split(None, 3)
        if len(parts) < 4:
            raise ValueError("Draft command format: draft <item_code> <qty> <supplier> [notes]")

        item_code = parts[1]
        quantity = int(parts[2])
        supplier_name = parts[3]
        notes = ""
        if len(parts) > 4:
            notes = parts[4]
        return orchestrator.create_draft_requisition(
            item_code=item_code,
            quantity=quantity,
            supplier_name=supplier_name,
            notes=notes,
        )

    return None


def main():

    print("=" * 60)
    print("SME PROCUREMENT PREPARATION AGENT")
    print("WEEK 3 - RAG PIPELINE")
    print("=" * 60)

    rag = RAGPipeline()
    orchestrator = AppToolOrchestrator()

    print(
        "\nRAG pipeline is ready."
    )

    print(TOOL_EXAMPLES)
    print(
        "Type 'exit' to stop.\n"
    )


    while True:

        question = input(
            "Procurement question: "
        ).strip()


        if question.lower() == "exit":

            print(
                "\nExiting RAG pipeline."
            )

            break


        if not question:

            print(
                "Please enter a question."
            )

            continue

        if question.lower().startswith("inventory") or question.lower().startswith("draft "):
            try:
                result = run_tool_command(question, orchestrator)
                print("\n" + "=" * 60)
                print("APPLICATION TOOL RESULT")
                print("=" * 60)
                print(result)
                print("\n")
            except Exception as error:
                print("\n[ERROR]")
                print(error)
            continue


        try:

            result = rag.generate_answer(
                question,
                top_k=5
            )


            print(
                "\n" + "=" * 60
            )

            print(
                "GROUNDED ANSWER"
            )

            print(
                "=" * 60
            )

            print(
                result["answer"]
            )


            display_sources(
                result["sources"]
            )


            print(
                "\n"
            )


        except Exception as error:

            print(
                "\n[ERROR]"
            )

            print(
                error
            )


if __name__ == "__main__":

    main()