import json
from typing import Any, LiteralString

import anthropic
from pydantic import BaseModel, Field

from app.config import ConfigError, Settings
from app.graph import Neo4jClient
from app.retrieval import QueryResult

SCHEMA = """\
Nodes (all IDs are strings):
  (:Brand    {brand_id, name, country})
  (:Category {category_id, name, description})
  (:Vendor   {vendor_id, name, city, state, speciality})
  (:Product  {product_id, name, price_inr: INTEGER, description})
  (:Customer {customer_id, name, email, city, state})
  (:Order    {order_id, order_date: DATE, status, payment_method, delivery_note (only on some)})

Relationships:
  (:Customer)-[:PLACED]->(:Order)
  (:Order)-[:CONTAINS {order_item_id, quantity: INTEGER, unit_price_inr: INTEGER}]->(:Product)
  (:Product)-[:MADE_BY]->(:Brand)
  (:Product)-[:BELONGS_TO]->(:Category)
  (:Product)-[:SUPPLIED_BY]->(:Vendor)
"""

CYPHER_SYSTEM = f"""\
You translate questions about an e-commerce store into one read-only Neo4j Cypher query.

Graph schema:
{SCHEMA}
Rules:
- Use only the labels, relationship types, directions and properties in the schema.
- Read-only: MATCH, OPTIONAL MATCH, WITH, UNWIND, WHERE, RETURN, ORDER BY, LIMIT. Never
  CREATE, MERGE, SET, DELETE, REMOVE, DROP, LOAD CSV, FOREACH, CALL or SHOW.
- One statement, no semicolon, no comments, no $parameters (write literal values).
- Use the exact names from the vocabulary below. For free text a user typed that is not in the
  vocabulary, match case-insensitively: toLower(x) CONTAINS toLower('...').
- Return named columns (RETURN p.name AS product), not whole nodes, and include IDs and
  names so the answer can cite them. Add ORDER BY for a stable order.
- Money: order line value = item.quantity * item.unit_price_inr, in INR. Unless the question
  says otherwise, revenue and spending exclude orders with status 'Cancelled'.
- Dates: o.order_date is a DATE, compare with date('2026-03-01').
- To find a word anywhere in the graph (e.g. 'banana'), scan every string property:
  MATCH (n) UNWIND keys(n) AS property WITH n, property, n[property] AS value
  WHERE value IS :: STRING AND toLower(value) CONTAINS 'word'
  RETURN labels(n)[0] AS label, coalesce(n.name, n.order_id) AS entity, property, value
- If the question cannot be answered from this graph (other topics, or data the schema does
  not have), set answerable to false and explain why in reason. Do not guess.
"""

ANSWER_SYSTEM = """\
You answer questions about an e-commerce store using ONLY the query results you are given.

- Every fact in your answer must come from the rows. Do not add products, names, numbers or
  explanations from general knowledge, and do not guess missing values.
- If the rows do not answer the question, say that the knowledge graph has no data for it.
- Use names, IDs and numbers exactly as they appear in the rows. Amounts are in INR: write
  them in Indian format, e.g. Rs 1,39,800.
- Do not speculate about the data, how it is stored or what the rows might mean beyond
  what they show.
- If the results are marked truncated, say the list is partial.
- Be concise: a direct answer, then a short list if there are several items.
"""

VOCABULARY_QUERIES: dict[str, LiteralString] = {
    "brands": "MATCH (b:Brand) RETURN b.name AS value ORDER BY value",
    "categories": "MATCH (c:Category) RETURN c.name AS value ORDER BY value",
    "vendors": "MATCH (v:Vendor) RETURN v.vendor_id + ' = ' + v.name AS value ORDER BY value",
    "order statuses": "MATCH (o:Order) RETURN DISTINCT o.status AS value ORDER BY value",
    "payment methods": "MATCH (o:Order) RETURN DISTINCT o.payment_method AS value ORDER BY value",
}


class LlmError(Exception):
    pass


class CypherPlan(BaseModel):
    answerable: bool = Field(description="false if the graph cannot answer the question")
    cypher: str = Field(description="the read-only Cypher query; empty if not answerable")
    reason: str = Field(description="why the question is not answerable; empty otherwise")


def graph_vocabulary(client: Neo4jClient) -> str:
    lines = []
    for name, cypher in VOCABULARY_QUERIES.items():
        values = [str(row["value"]) for row in client.read(cypher)]
        lines.append(f"{name}: {', '.join(values)}")
    return "\n".join(lines)


def rows_as_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=1, default=str)


class LlmClient:
    def __init__(self, settings: Settings) -> None:
        if settings.anthropic_api_key is None:
            raise ConfigError("ANTHROPIC_API_KEY is not set. Add it to .env to ask questions.")
        workspace = settings.anthropic_workspace_id
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            default_headers={"anthropic-workspace-id": workspace} if workspace else None,
        )
        self._model = settings.llm_model

    def generate_cypher(self, question: str, vocabulary: str, feedback: list[str]) -> CypherPlan:
        prompt = f"Vocabulary (exact values in the graph):\n{vocabulary}\n\nQuestion: {question}"
        if feedback:
            prompt += "\n\nYour earlier queries for this question were rejected:\n"
            prompt += "\n".join(feedback)
            prompt += "\nWrite a corrected query."
        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=16000,
                system=CYPHER_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                output_format=CypherPlan,
                output_config={"effort": "medium"},
            )
        except anthropic.APIError as exc:
            raise LlmError(f"Cypher generation failed: {exc}") from exc
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise LlmError(f"Cypher generation returned no plan (stop: {response.stop_reason})")
        return response.parsed_output

    def write_answer(self, question: str, result: QueryResult) -> str:
        prompt = (
            f"Question: {question}\n\n"
            f"Cypher that was run:\n{result.cypher}\n\n"
            f"Results ({len(result.rows)} rows{', TRUNCATED' if result.truncated else ''}):\n"
            f"{rows_as_json(result.rows)}"
        )
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=16000,
                system=ANSWER_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "low"},
            )
        except anthropic.APIError as exc:
            raise LlmError(f"Answer generation failed: {exc}") from exc
        text = "".join(block.text for block in response.content if block.type == "text")
        if response.stop_reason == "refusal" or not text.strip():
            raise LlmError(f"Answer generation returned no text (stop: {response.stop_reason})")
        return text.strip()
