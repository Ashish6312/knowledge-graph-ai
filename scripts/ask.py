import sys

import _bootstrap  # noqa: F401
from neo4j.exceptions import AuthError, ServiceUnavailable

from app.config import ConfigError, load_settings
from app.graph import Neo4jClient
from app.llm import LlmClient, LlmError, graph_vocabulary, rows_as_json
from app.qa import Answer, answer_question

MAX_ROWS_SHOWN = 15


def show(answer: Answer) -> None:
    for rejected in answer.rejected:
        print(f"[rejected attempt]\n{rejected}\n")
    if answer.cypher:
        print(f"[cypher]\n{answer.cypher}\n")
        more = " (truncated)" if answer.truncated else ""
        print(f"[retrieved {len(answer.rows)} row(s){more}]")
        print(rows_as_json(answer.rows[:MAX_ROWS_SHOWN]))
        if len(answer.rows) > MAX_ROWS_SHOWN:
            print(f"... {len(answer.rows) - MAX_ROWS_SHOWN} more rows")
        print()
    print(f"[answer]\n{answer.answer}\n")


def main() -> int:
    try:
        settings = load_settings()
        llm = LlmClient(settings)
    except ConfigError as exc:
        print(exc)
        return 1

    interactive = len(sys.argv) == 1
    with Neo4jClient(settings) as client:
        try:
            client.verify_connectivity()
        except (ServiceUnavailable, AuthError) as exc:
            print(f"Cannot connect to Neo4j at {settings.neo4j_uri}: {str(exc).splitlines()[0]}")
            print("Is it running? Start it with: docker compose up -d --wait")
            return 1
        vocabulary = graph_vocabulary(client)
        question = read_question() if interactive else " ".join(sys.argv[1:])
        while question:
            try:
                show(answer_question(question, client, llm, vocabulary, settings.max_result_rows))
            except LlmError as exc:
                print(f"LLM error: {exc}\n")
            question = read_question() if interactive else ""
    return 0


def read_question() -> str:
    try:
        return input("Question> ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


if __name__ == "__main__":
    sys.exit(main())
