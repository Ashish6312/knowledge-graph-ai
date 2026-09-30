import re
from dataclasses import dataclass
from typing import LiteralString

from app.dataset import BANANA, EXPECTED_BANANA_COUNT, CheckResult
from app.graph import Neo4jClient

EXPECTED_NODES = {
    "Brand": 10,
    "Category": 9,
    "Vendor": 9,
    "Product": 45,
    "Customer": 25,
    "Order": 40,
}
EXPECTED_RELATIONSHIPS = {
    "PLACED": 40,
    "CONTAINS": 84,
    "MADE_BY": 45,
    "BELONGS_TO": 45,
    "SUPPLIED_BY": 45,
}
EXPECTED_CONSTRAINTS = {
    ("Brand", "brand_id"),
    ("Category", "category_id"),
    ("Vendor", "vendor_id"),
    ("Product", "product_id"),
    ("Customer", "customer_id"),
    ("Order", "order_id"),
}

NODE_COUNTS: LiteralString = """
MATCH (n)
UNWIND labels(n) AS label
RETURN label, count(*) AS count
"""

RELATIONSHIP_COUNTS: LiteralString = """
MATCH ()-[r]->()
RETURN type(r) AS type, count(*) AS count
"""

DUPLICATE_RELATIONSHIPS: LiteralString = """
MATCH (a)-[r]->(b)
WITH a, b, type(r) AS type, count(r) AS copies
WHERE copies > 1
RETURN count(*) AS duplicates
"""

UNIQUENESS_CONSTRAINTS: LiteralString = """
SHOW CONSTRAINTS YIELD type, labelsOrTypes, properties
WHERE type = 'UNIQUENESS'
RETURN labelsOrTypes[0] AS label, properties[0] AS property
"""

BANANA_PROPERTIES: LiteralString = """
MATCH (n)
UNWIND keys(n) AS property
WITH n, property, n[property] AS value
WHERE value IS :: STRING AND value =~ $pattern
RETURN labels(n)[0] AS label,
       coalesce(n.product_id, n.category_id, n.vendor_id, n.order_id,
                n.customer_id, n.brand_id) AS id,
       property,
       value
ORDER BY label, id
"""

BANANA_RELATIONSHIP_PROPERTIES: LiteralString = """
MATCH ()-[r]->()
UNWIND keys(r) AS property
WITH r, property, r[property] AS value
WHERE value IS :: STRING AND value =~ $pattern
RETURN type(r) AS label, elementId(r) AS id, property, value
"""

BANANA_PATTERN = rf"(?is).*\b{BANANA}\b.*"
_BANANA_WORD = re.compile(rf"\b{BANANA}\b", re.IGNORECASE)


@dataclass(frozen=True)
class GraphBanana:
    label: str
    entity_id: str
    property: str
    value: str
    occurrences: int


def node_counts(client: Neo4jClient) -> dict[str, int]:
    return {row["label"]: row["count"] for row in client.read(NODE_COUNTS)}


def relationship_counts(client: Neo4jClient) -> dict[str, int]:
    return {row["type"]: row["count"] for row in client.read(RELATIONSHIP_COUNTS)}


def duplicate_relationships(client: Neo4jClient) -> int:
    count: int = client.read(DUPLICATE_RELATIONSHIPS)[0]["duplicates"]
    return count


def uniqueness_constraints(client: Neo4jClient) -> set[tuple[str, str]]:
    return {(row["label"], row["property"]) for row in client.read(UNIQUENESS_CONSTRAINTS)}


def banana_in_graph(client: Neo4jClient) -> list[GraphBanana]:
    rows = client.read(BANANA_PROPERTIES, pattern=BANANA_PATTERN)
    rows += client.read(BANANA_RELATIONSHIP_PROPERTIES, pattern=BANANA_PATTERN)
    return [
        GraphBanana(
            label=row["label"],
            entity_id=str(row["id"]),
            property=row["property"],
            value=row["value"],
            occurrences=len(_BANANA_WORD.findall(row["value"])),
        )
        for row in rows
    ]


def _compare(name: str, expected: dict[str, int], actual: dict[str, int]) -> CheckResult:
    problems = [
        f"{key}: expected {expected.get(key, 0)}, found {actual.get(key, 0)}"
        for key in sorted(set(expected) | set(actual))
        if expected.get(key, 0) != actual.get(key, 0)
    ]
    return CheckResult(name, not problems, problems)


def verify_graph(client: Neo4jClient) -> list[CheckResult]:
    missing = EXPECTED_CONSTRAINTS - uniqueness_constraints(client)
    duplicates = duplicate_relationships(client)
    bananas = banana_in_graph(client)
    total_bananas = sum(b.occurrences for b in bananas)
    return [
        CheckResult(
            "uniqueness constraints exist",
            not missing,
            [f"missing constraint on {label}.{prop}" for label, prop in sorted(missing)],
        ),
        _compare("node counts", EXPECTED_NODES, node_counts(client)),
        _compare("relationship counts", EXPECTED_RELATIONSHIPS, relationship_counts(client)),
        CheckResult(
            "no duplicate relationships",
            duplicates == 0,
            [f"{duplicates} node pairs have repeated relationships"] if duplicates else [],
        ),
        CheckResult(
            f"exactly {EXPECTED_BANANA_COUNT} x '{BANANA}' in graph properties",
            total_bananas == EXPECTED_BANANA_COUNT,
            []
            if total_bananas == EXPECTED_BANANA_COUNT
            else [f"found {total_bananas}, expected {EXPECTED_BANANA_COUNT}"],
        ),
    ]
