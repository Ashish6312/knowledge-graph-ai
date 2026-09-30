from dataclasses import dataclass, field
from typing import Any, Protocol

from neo4j.exceptions import Neo4jError

from app.graph import Neo4jClient
from app.llm import CypherPlan
from app.retrieval import QueryResult, UnsafeCypherError, run_read_query

MAX_ATTEMPTS = 3
NO_DATA_ANSWER = "The knowledge graph has no data matching this question."


class Llm(Protocol):
    def generate_cypher(
        self, question: str, vocabulary: str, feedback: list[str]
    ) -> CypherPlan: ...

    def write_answer(self, question: str, result: QueryResult) -> str: ...


@dataclass(frozen=True)
class Answer:
    question: str
    answer: str
    cypher: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    rejected: list[str] = field(default_factory=list)


def answer_question(
    question: str, client: Neo4jClient, llm: Llm, vocabulary: str, max_rows: int
) -> Answer:
    feedback: list[str] = []
    for _ in range(MAX_ATTEMPTS):
        plan = llm.generate_cypher(question, vocabulary, feedback)
        if not plan.answerable:
            return Answer(
                question,
                f"This question cannot be answered from the knowledge graph: {plan.reason}",
                rejected=feedback,
            )
        try:
            result = run_read_query(client, plan.cypher, max_rows)
        except (UnsafeCypherError, Neo4jError) as exc:
            feedback.append(f"- query: {plan.cypher}\n  error: {exc}")
            continue

        text = llm.write_answer(question, result) if result.rows else NO_DATA_ANSWER
        return Answer(question, text, result.cypher, result.rows, result.truncated, feedback)

    return Answer(
        question,
        f"Could not build a valid query for this question in {MAX_ATTEMPTS} attempts.",
        rejected=feedback,
    )
