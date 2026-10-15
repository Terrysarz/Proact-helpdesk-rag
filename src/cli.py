"""
Terminal-chat met de Service Desk Assistant (niet-streamend, handig als snelle test).

    python src/cli.py
"""

from rag import answer_once


def main() -> None:
    print("=" * 60)
    print(" Proact Service Desk Assistant  (lokale RAG-PoC)")
    print(" Typ je vraag. Stop met 'exit' of 'quit'.")
    print("=" * 60)

    session: dict = {}   # bewaart staat tussen berichten (reset-flow etc.)

    while True:
        try:
            question = input("\nJij> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nTot ziens!")
            break

        if question.lower() in ("exit", "quit", "stop"):
            print("Tot ziens!")
            break
        if not question:
            continue

        result = answer_once(question, session)
        print("\nAssistant>", result["text"])
        if result["sources"]:
            print("Bronnen:", ", ".join(result["sources"]))


if __name__ == "__main__":
    main()
