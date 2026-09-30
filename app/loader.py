from dataclasses import dataclass
from typing import Any, LiteralString

import pandas as pd

from app.dataset import Tables
from app.graph import Neo4jClient

CONSTRAINTS: tuple[LiteralString, ...] = (
    "CREATE CONSTRAINT brand_id IF NOT EXISTS FOR (b:Brand) REQUIRE b.brand_id IS UNIQUE",
    "CREATE CONSTRAINT category_id IF NOT EXISTS FOR (c:Category) REQUIRE c.category_id IS UNIQUE",
    "CREATE CONSTRAINT vendor_id IF NOT EXISTS FOR (v:Vendor) REQUIRE v.vendor_id IS UNIQUE",
    "CREATE CONSTRAINT product_id IF NOT EXISTS FOR (p:Product) REQUIRE p.product_id IS UNIQUE",
    "CREATE CONSTRAINT customer_id IF NOT EXISTS FOR (c:Customer) REQUIRE c.customer_id IS UNIQUE",
    "CREATE CONSTRAINT order_id IF NOT EXISTS FOR (o:Order) REQUIRE o.order_id IS UNIQUE",
)

LOAD_BRANDS: LiteralString = """
UNWIND $rows AS row
MERGE (b:Brand {brand_id: row.brand_id})
SET b.name = row.name, b.country = row.country
"""

LOAD_CATEGORIES: LiteralString = """
UNWIND $rows AS row
MERGE (c:Category {category_id: row.category_id})
SET c.name = row.name, c.description = row.description
"""

LOAD_VENDORS: LiteralString = """
UNWIND $rows AS row
MERGE (v:Vendor {vendor_id: row.vendor_id})
SET v.name = row.name, v.city = row.city, v.state = row.state, v.speciality = row.speciality
"""

LOAD_PRODUCTS: LiteralString = """
UNWIND $rows AS row
MATCH (b:Brand {brand_id: row.brand_id})
MATCH (c:Category {category_id: row.category_id})
MATCH (v:Vendor {vendor_id: row.vendor_id})
MERGE (p:Product {product_id: row.product_id})
SET p.name = row.name, p.price_inr = row.price_inr, p.description = row.description
MERGE (p)-[:MADE_BY]->(b)
MERGE (p)-[:BELONGS_TO]->(c)
MERGE (p)-[:SUPPLIED_BY]->(v)
"""

LOAD_CUSTOMERS: LiteralString = """
UNWIND $rows AS row
MERGE (c:Customer {customer_id: row.customer_id})
SET c.name = row.name, c.email = row.email, c.city = row.city, c.state = row.state
"""

LOAD_ORDERS: LiteralString = """
UNWIND $rows AS row
MATCH (c:Customer {customer_id: row.customer_id})
MERGE (o:Order {order_id: row.order_id})
SET o.order_date = date(row.order_date),
    o.status = row.status,
    o.payment_method = row.payment_method,
    o.delivery_note = row.delivery_note
MERGE (c)-[:PLACED]->(o)
"""

LOAD_ORDER_ITEMS: LiteralString = """
UNWIND $rows AS row
MATCH (o:Order {order_id: row.order_id})
MATCH (p:Product {product_id: row.product_id})
MERGE (o)-[r:CONTAINS]->(p)
SET r.order_item_id = row.order_item_id,
    r.quantity = row.quantity,
    r.unit_price_inr = row.unit_price_inr
"""

RESET_GRAPH: LiteralString = "MATCH (n) DETACH DELETE n"


@dataclass(frozen=True)
class StepResult:
    step: str
    rows: int
    nodes_created: int
    relationships_created: int
    properties_set: int


def _records(
    frame: pd.DataFrame, ints: tuple[str, ...] = (), optional: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = frame.to_dict("records")  # type: ignore[assignment]
    for row in rows:
        for column in ints:
            row[column] = int(row[column])
        for column in optional:
            row[column] = row[column] or None
    return rows


def create_constraints(client: Neo4jClient) -> None:
    for statement in CONSTRAINTS:
        client.write(statement)
    client.write("CALL db.awaitIndexes(60)")


def reset_graph(client: Neo4jClient) -> None:
    client.write(RESET_GRAPH)


def load_graph(client: Neo4jClient, tables: Tables) -> list[StepResult]:
    steps: list[tuple[str, LiteralString, list[dict[str, Any]]]] = [
        ("brands", LOAD_BRANDS, _records(tables["brands"])),
        ("categories", LOAD_CATEGORIES, _records(tables["categories"])),
        ("vendors", LOAD_VENDORS, _records(tables["vendors"])),
        ("products", LOAD_PRODUCTS, _records(tables["products"], ints=("price_inr",))),
        ("customers", LOAD_CUSTOMERS, _records(tables["customers"])),
        ("orders", LOAD_ORDERS, _records(tables["orders"], optional=("delivery_note",))),
        (
            "order_items",
            LOAD_ORDER_ITEMS,
            _records(tables["order_items"], ints=("quantity", "unit_price_inr")),
        ),
    ]
    results = []
    for name, cypher, rows in steps:
        counters = client.write(cypher, rows=rows)
        results.append(
            StepResult(
                step=name,
                rows=len(rows),
                nodes_created=counters.nodes_created,
                relationships_created=counters.relationships_created,
                properties_set=counters.properties_set,
            )
        )
    return results
