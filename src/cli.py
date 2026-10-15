"""
Eenvoudige terminal-chat met de Service Desk Assistant.
Handig als snelle demo en als fallback als je geen browser wilt tonen.

    python src/cli.py
"""

from rag import answer


def main() -> None:
    print("=" * 60)
    print(" Proact Service Desk Assistant  (lokale RAG-PoC)")
    print(" Typ je vraag. Stop met 'exit' of 'quit'.")
    print("=" * 60)

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

        result = answer(question)
        print("\nAssistant>", result["answer"])
        if result["sources"]:
            print("Bronnen:", ", ".join(result["sources"]))


if __name__ == "__main__":
    main()
