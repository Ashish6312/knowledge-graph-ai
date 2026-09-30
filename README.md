# Knowledge Graph AI

Natural-language question answering over an e-commerce knowledge graph stored in Neo4j.

A question is translated into Cypher by an LLM, the query is checked and executed against the
graph in a read-only transaction, and a second model call writes the answer from the returned
rows only. Every answer is returned together with the query and the rows it is based on.

```
Question ─▶ LLM (Cypher) ─▶ safety checks ─▶ Neo4j ─▶ rows ─▶ LLM (answer) ─▶ Answer
```

## Requirements

- Python 3.12+
- Docker Desktop (runs Neo4j 5.26 Community)
- An Anthropic API key

## Setup

```bash
git clone <repository-url> knowledge-graph-ai
cd knowledge-graph-ai

cp .env.example .env                 # set NEO4J_PASSWORD (8+ chars) and ANTHROPIC_API_KEY

python -m venv .venv
.venv\Scripts\activate               # Windows
source .venv/bin/activate            # macOS / Linux
pip install -r requirements.txt

docker compose up -d --wait          # start Neo4j and wait until it is healthy
python scripts/load_data.py          # validate CSVs, load the graph, verify it
```

`load_data.py` ends with a verification report; every line should read `PASS`.
If ports 7474/7687 are in use, change `NEO4J_HTTP_PORT` / `NEO4J_BOLT_PORT` in `.env` and
update `NEO4J_URI` to match.

## Usage

```bash
python scripts/ask.py "Which products from Apple are supplied by TechWorld Retail?"
python scripts/ask.py                       # interactive mode, empty line to exit
python scripts/run_sample_questions.py      # regenerate docs/sample_results.md
```

Example output:

```
[cypher]
MATCH (p:Product)-[:MADE_BY]->(b:Brand {name: 'Apple'}),
      (p)-[:SUPPLIED_BY]->(v:Vendor {vendor_id: 'V001'})
RETURN p.product_id AS product_id, p.name AS product, p.price_inr AS price_inr, ...

[retrieved 3 row(s)]
[ {"product_id": "P001", "product": "iPhone 16 128GB", ...}, ... ]

[answer]
TechWorld Retail (V001) supplies 3 Apple products:
- P001 – iPhone 16 128GB – Rs 79,900
- P002 – iPhone 15 128GB – Rs 69,900
- P006 – iPad Air 11 M2 – Rs 59,900
```

Other utilities:

| Command | Purpose |
|---|---|
| `python scripts/validate_dataset.py` | Validate the CSV files without touching Neo4j |
| `python scripts/verify_graph.py` | Node/relationship counts and integrity checks from Neo4j |
| `python scripts/validate_banana.py` | List every `banana` occurrence stored in the graph |
| `python scripts/run_queries.py [n ...]` | Run the hand-written reference Cypher queries |
| `python scripts/load_data.py --reset` | Clear the graph and reload it |

## Knowledge graph

### Schema

```
(:Customer)-[:PLACED]->(:Order)-[:CONTAINS {order_item_id, quantity, unit_price_inr}]->(:Product)
(:Product)-[:MADE_BY]->(:Brand)
(:Product)-[:BELONGS_TO]->(:Category)
(:Product)-[:SUPPLIED_BY]->(:Vendor)
```

138 nodes, 259 relationships.

| Node | Count | Key | Properties |
|---|---|---|---|
| `Brand` | 10 | `brand_id` | `name`, `country` |
| `Category` | 9 | `category_id` | `name`, `description` |
| `Vendor` | 9 | `vendor_id` | `name`, `city`, `state`, `speciality` |
| `Product` | 45 | `product_id` | `name`, `price_inr` (int), `description` |
| `Customer` | 25 | `customer_id` | `name`, `email`, `city`, `state` |
| `Order` | 40 | `order_id` | `order_date` (date), `status`, `payment_method`, `delivery_note` (optional) |

| Relationship | Direction | Count |
|---|---|---|
| `PLACED` | Customer → Order | 40 |
| `CONTAINS` | Order → Product | 84 |
| `MADE_BY` | Product → Brand | 45 |
| `BELONGS_TO` | Product → Category | 45 |
| `SUPPLIED_BY` | Product → Vendor | 45 |

### Design notes

- Brand, Category and Vendor are separate nodes rather than product attributes, so queries
  such as "all Philips products" start from one node and follow relationships.
- Order lines are modelled as properties on `CONTAINS` (quantity, unit price). An order line
  links exactly one order to one product and nothing else references it.
- Prices and quantities are stored as integers and `order_date` as a Neo4j `DATE`, so
  aggregation and date filtering work without conversion.
- Each ID has a uniqueness constraint, which also provides the index used by `MERGE`.
- The loader uses `UNWIND ... MERGE` per entity type, one transaction per step, and is
  idempotent: a second run creates 0 nodes and 0 relationships.

Neo4j was chosen because every question is a relationship chain
(customer → order → product → brand/vendor). In Cypher this is a single short pattern, which
is both easier for an LLM to generate correctly and easier for a person to review.

## Dataset

Seven CSV files in `data/`, generated for an Indian online store (prices in INR).

| File | Rows | Columns |
|---|---|---|
| `brands.csv` | 10 | `brand_id`, `name`, `country` |
| `categories.csv` | 9 | `category_id`, `name`, `description` |
| `vendors.csv` | 9 | `vendor_id`, `name`, `city`, `state`, `speciality` |
| `products.csv` | 45 | `product_id`, `name`, `brand_id`, `category_id`, `vendor_id`, `price_inr`, `description` |
| `customers.csv` | 25 | `customer_id`, `name`, `email`, `city`, `state` |
| `orders.csv` | 40 | `order_id`, `customer_id`, `order_date`, `status`, `payment_method`, `delivery_note` |
| `order_items.csv` | 84 | `order_item_id`, `order_id`, `product_id`, `quantity`, `unit_price_inr` |

Before loading, `app/dataset.py` runs nine checks: required values, unique IDs and names,
valid references, no orphan records, valid prices and quantities, valid dates, statuses and
payment methods, row counts, and the `banana` count. Nothing is written if any check fails.

## Retrieval pipeline

The pipeline lives in `app/qa.py` (`answer_question`).

1. **Cypher generation** (`app/llm.py`). The system prompt contains the graph schema and query
   rules. The user message adds a vocabulary read live from the graph (brand, category and
   vendor names, order statuses, payment methods) so the model uses exact values. The response
   is structured output validated with Pydantic: `{answerable, cypher, reason}`. Questions
   outside the graph's scope are marked unanswerable and no query is run.
2. **Safety checks** (`app/retrieval.py`). The generated query is treated as untrusted input:
   - text rules: single statement, must start with a read clause, no write/schema/procedure
     keywords (checked after removing string literals and comments);
   - `EXPLAIN` must report the query type as read-only;
   - execution in a `READ` transaction, so the server rejects any write;
   - per-query timeout and row limit.
3. **Retry.** If a query is rejected or fails in Neo4j, the error is returned to the model and
   it produces a corrected query (up to 3 attempts).
4. **Answer generation.** The second call receives only the question, the executed Cypher and
   the rows as JSON.

## Grounding

- The answer model never sees the schema, the CSVs or the database, only the retrieved rows.
- Its system prompt forbids outside knowledge and requires a "no data" reply when the rows do
  not answer the question.
- If the query returns no rows, the model is not called; the answer is the fixed text
  *"The knowledge graph has no data matching this question."*
- Each answer is returned with its Cypher and rows, so every statement can be checked.

For example, *"Which products does Sony make?"* returns no rows (Sony is not in the graph) and
produces the fixed no-data answer; *"What will the weather be in Mumbai tomorrow?"* is
classified as unanswerable and no query runs.

## The `banana` value

`banana` is stored exactly five times, as ordinary text in property values, and is linked
through a single order so it can be found both by search and by traversal:

| Node | Property | Value |
|---|---|---|
| Category `C005` | `description` | Packaged namkeen, sweets and banana chips. |
| Order `ORD016` | `delivery_note` | Please pack the banana chips separately from the blender |
| Product `P022` | `description` | 300 W hand blender, handy for banana shakes and purees. |
| Product `P029` | `description` | Crispy Kerala-style banana chips fried in coconut oil. |
| Vendor `V005` | `speciality` | Dry fruits, namkeen and Kerala banana chips wholesaler |

Customer `CU015` placed `ORD016`, which contains `P022` and `P029`; `P029` belongs to `C005` and
is supplied by `V005`.

It can be retrieved through the assistant
(`python scripts/ask.py "Where does the word banana appear in the knowledge graph?"`), with
`python scripts/validate_banana.py`, or directly in Neo4j Browser:

```cypher
MATCH (n) UNWIND keys(n) AS property
WITH n, property, n[property] AS value
WHERE value IS :: STRING AND value =~ '(?i)(.*[^a-z])?banana([^a-z].*)?'
RETURN labels(n)[0] AS label, property, value
```

## Sample questions

Full output (generated Cypher, retrieved rows, answer) is in
[docs/sample_results.md](docs/sample_results.md).

| # | Question | Result |
|---|---|---|
| 1 | Which products from Apple are supplied by TechWorld Retail? | P001, P002, P006 |
| 2 | Which customers have bought Apple products? | CU001, CU008, CU012, CU013, CU019, CU021 |
| 3 | Top 5 best-selling products by units sold, excluding cancelled orders | P029 (11 units), P035, P036, P016, P033 |
| 4 | Where does the word banana appear in the knowledge graph? | 5 properties: C005, ORD016, P022, P029, V005 |
| 5 | Which customers have spent at least Rs 1,00,000? | 5 customers, CU019 highest at Rs 1,57,197 |
| 6 | What did CU015 buy, and which vendor supplied each product? | P029 ×6, P031 ×2 (V005); P022 ×1 (V004) |
| 7 | Which brands have products in cancelled orders? | Apple, Samsung (ORD026); Prestige (ORD009) |
| 8 | Which products does Sony make? | No rows; fixed no-data answer |
| 9 | What will the weather be in Mumbai tomorrow? | Unanswerable; no query run |

## Viewing the graph

Open Neo4j Browser at `http://localhost:<NEO4J_HTTP_PORT>` (default 7474) and connect to the
same Bolt URL as `NEO4J_URI` in `.env`, using the `.env` credentials. If another Neo4j instance
runs on the machine, make sure the Browser is connected to this one; otherwise the graph will
appear empty.

```cypher
MATCH (n) RETURN n LIMIT 200

MATCH path = (:Customer)-[:PLACED]->(:Order {order_id: 'ORD016'})-[:CONTAINS]->(:Product)
             -[:MADE_BY|BELONGS_TO|SUPPLIED_BY]->()
RETURN path
```

## Project structure

```
app/
  config.py            settings from environment variables
  dataset.py           CSV loading and validation
  graph.py             Neo4j client (read, write, read-only execution, EXPLAIN)
  loader.py            constraints and MERGE statements
  graph_checks.py      graph verification queries
  example_queries.py   hand-written reference Cypher queries
  retrieval.py         validation and execution of generated Cypher
  llm.py               prompts and LLM client
  qa.py                question-answering pipeline
data/                  CSV dataset
docs/                  sample question results
scripts/               command-line entry points
```

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEO4J_URI` | yes | | Bolt URI, e.g. `bolt://localhost:7687` |
| `NEO4J_USER` | yes | | Neo4j user |
| `NEO4J_PASSWORD` | yes | | Neo4j password (min. 8 characters) |
| `NEO4J_DATABASE` | no | `neo4j` | Database name |
| `NEO4J_HTTP_PORT` / `NEO4J_BOLT_PORT` | no | `7474` / `7687` | Host ports for the container |
| `QUERY_TIMEOUT_SECONDS` | no | `10` | Timeout per graph query |
| `MAX_RESULT_ROWS` | no | `100` | Maximum rows passed to the answer step |
| `ANTHROPIC_API_KEY` | for questions | | Anthropic API key |
| `LLM_MODEL` | no | `claude-opus-5-5` | Model name |
| `ANTHROPIC_WORKSPACE_ID` | no | | Only for keys not scoped to a workspace |

## Limitations

- Grounding is enforced by what the answer model receives, not by checking each sentence of the
  answer against the rows afterwards. Simple arithmetic over the rows (e.g. totals) is done by
  the model.
- The keyword filter is conservative and may reject some valid read queries (for example
  `CALL { ... }` subqueries); read-only safety is guaranteed by the `EXPLAIN` check and the
  `READ` transaction.
- Neo4j Community Edition has no role-based access control, so the application connects as the
  admin user and enforces read-only access per transaction.
- Results larger than `MAX_RESULT_ROWS` are truncated; the answer states that the list is partial.
