from dataclasses import dataclass, field
from typing import Any, LiteralString

from app.graph_checks import BANANA_PATTERN, BANANA_PROPERTIES


@dataclass(frozen=True)
class ExampleQuery:
    number: int
    question: str
    cypher: LiteralString
    params: dict[str, Any] = field(default_factory=dict)


EXAMPLES: tuple[ExampleQuery, ...] = (
    ExampleQuery(
        1,
        "List all products.",
        """
MATCH (p:Product)
RETURN p.product_id AS product_id, p.name AS product, p.price_inr AS price_inr
ORDER BY product_id
""",
    ),
    ExampleQuery(
        2,
        "Which products are made by Philips?",
        """
MATCH (p:Product)-[:MADE_BY]->(b:Brand)
WHERE b.name = $brand
RETURN p.product_id AS product_id, p.name AS product, p.price_inr AS price_inr
ORDER BY product_id
""",
        {"brand": "Philips"},
    ),
    ExampleQuery(
        3,
        "Which products does vendor V005 supply?",
        """
MATCH (p:Product)-[:SUPPLIED_BY]->(v:Vendor {vendor_id: $vendor_id})
RETURN v.name AS vendor, p.product_id AS product_id, p.name AS product
ORDER BY product_id
""",
        {"vendor_id": "V005"},
    ),
    ExampleQuery(
        4,
        "Which products are in the Kitchen Appliances category?",
        """
MATCH (p:Product)-[:BELONGS_TO]->(c:Category {name: $category})
RETURN p.product_id AS product_id, p.name AS product, p.price_inr AS price_inr
ORDER BY product_id
""",
        {"category": "Kitchen Appliances"},
    ),
    ExampleQuery(
        5,
        "Which Apple products are supplied by vendor V001?",
        """
MATCH (b:Brand {name: $brand})<-[:MADE_BY]-(p:Product)-[:SUPPLIED_BY]->(v:Vendor)
WHERE v.vendor_id = $vendor_id
RETURN p.product_id AS product_id, p.name AS product, v.name AS vendor
ORDER BY product_id
""",
        {"brand": "Apple", "vendor_id": "V001"},
    ),
    ExampleQuery(
        6,
        "Which products has customer CU015 bought, and how many of each?",
        """
MATCH (c:Customer {customer_id: $customer_id})-[:PLACED]->(o:Order)-[item:CONTAINS]->(p:Product)
RETURN p.product_id AS product_id, p.name AS product,
       sum(item.quantity) AS total_quantity,
       collect(o.order_id) AS orders
ORDER BY total_quantity DESC, product_id
""",
        {"customer_id": "CU015"},
    ),
    ExampleQuery(
        7,
        "Which customers bought Apple products?",
        """
MATCH (c:Customer)-[:PLACED]->(:Order)-[:CONTAINS]->(:Product)-[:MADE_BY]->(:Brand {name: $brand})
RETURN DISTINCT c.customer_id AS customer_id, c.name AS customer, c.city AS city
ORDER BY customer_id
""",
        {"brand": "Apple"},
    ),
    ExampleQuery(
        8,
        "Which customers bought products supplied by vendor V005, and what did they buy?",
        """
MATCH (c:Customer)-[:PLACED]->(o:Order)-[:CONTAINS]->(p:Product)-[:SUPPLIED_BY]->(v:Vendor)
WHERE v.vendor_id = $vendor_id
RETURN c.customer_id AS customer_id, c.name AS customer,
       count(DISTINCT o) AS orders,
       collect(DISTINCT p.name) AS products
ORDER BY customer_id
""",
        {"vendor_id": "V005"},
    ),
    ExampleQuery(
        9,
        "What are the 5 most purchased products by quantity (excluding cancelled orders)?",
        """
MATCH (o:Order)-[item:CONTAINS]->(p:Product)
WHERE o.status <> 'Cancelled'
RETURN p.product_id AS product_id, p.name AS product,
       sum(item.quantity) AS units_sold,
       count(o) AS orders
ORDER BY units_sold DESC, orders DESC, product_id
LIMIT $limit
""",
        {"limit": 5},
    ),
    ExampleQuery(
        10,
        "Where does the word 'banana' occur in the knowledge graph?",
        BANANA_PROPERTIES,
        {"pattern": BANANA_PATTERN},
    ),
    ExampleQuery(
        11,
        "How many cancelled orders involve each brand (including brands with none)?",
        """
MATCH (b:Brand)
OPTIONAL MATCH (b)<-[:MADE_BY]-(:Product)<-[:CONTAINS]-(o:Order {status: 'Cancelled'})
RETURN b.name AS brand, count(DISTINCT o) AS cancelled_orders
ORDER BY cancelled_orders DESC, brand
""",
    ),
    ExampleQuery(
        12,
        "Which customers have spent at least Rs 1,00,000 (excluding cancelled orders)?",
        """
MATCH (c:Customer)-[:PLACED]->(o:Order)-[item:CONTAINS]->(:Product)
WHERE o.status <> 'Cancelled'
WITH c, sum(item.quantity * item.unit_price_inr) AS spent
WHERE spent >= $min_spend
RETURN c.customer_id AS customer_id, c.name AS customer, spent
ORDER BY spent DESC
""",
        {"min_spend": 100000},
    ),
    ExampleQuery(
        13,
        "Follow the banana order ORD016: who placed it, what it contains, and each product's "
        "brand, category and vendor.",
        """
MATCH (c:Customer)-[:PLACED]->(o:Order {order_id: $order_id})-[item:CONTAINS]->(p:Product)
MATCH (p)-[:MADE_BY]->(b:Brand),
      (p)-[:BELONGS_TO]->(cat:Category),
      (p)-[:SUPPLIED_BY]->(v:Vendor)
RETURN c.name AS customer, o.delivery_note AS delivery_note,
       p.name AS product, item.quantity AS quantity,
       b.name AS brand, cat.name AS category, v.name AS vendor
ORDER BY product
""",
        {"order_id": "ORD016"},
    ),
)
