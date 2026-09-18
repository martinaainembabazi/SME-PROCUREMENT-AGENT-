"""
Command-line interface for the SME Procurement
Preparation RAG system.
"""

from rag import RAGPipeline
import os

MODEL_NAME = os.getenv(
    "GEMINI_MODEL",
    os.getenv("MODEL_NAME", "gemini-2.5-flash")
)


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


def main():

    print("=" * 60)
    print("SME PROCUREMENT PREPARATION AGENT")
    print("WEEK 3 - RAG PIPELINE")
    print("=" * 60)

    rag = RAGPipeline()

    print(
        "\nRAG pipeline is ready."
    )

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