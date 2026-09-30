import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class TableSpec:
    file: str
    id_column: str
    columns: tuple[str, ...]
    optional: frozenset[str] = frozenset()


TABLES: dict[str, TableSpec] = {
    "brands": TableSpec("brands.csv", "brand_id", ("brand_id", "name", "country")),
    "categories": TableSpec(
        "categories.csv", "category_id", ("category_id", "name", "description")
    ),
    "vendors": TableSpec(
        "vendors.csv", "vendor_id", ("vendor_id", "name", "city", "state", "speciality")
    ),
    "products": TableSpec(
        "products.csv",
        "product_id",
        ("product_id", "name", "brand_id", "category_id", "vendor_id", "price_inr", "description"),
    ),
    "customers": TableSpec(
        "customers.csv", "customer_id", ("customer_id", "name", "email", "city", "state")
    ),
    "orders": TableSpec(
        "orders.csv",
        "order_id",
        ("order_id", "customer_id", "order_date", "status", "payment_method", "delivery_note"),
        optional=frozenset({"delivery_note"}),
    ),
    "order_items": TableSpec(
        "order_items.csv",
        "order_item_id",
        ("order_item_id", "order_id", "product_id", "quantity", "unit_price_inr"),
    ),
}

FOREIGN_KEYS = (
    ("products", "brand_id", "brands"),
    ("products", "category_id", "categories"),
    ("products", "vendor_id", "vendors"),
    ("orders", "customer_id", "customers"),
    ("order_items", "order_id", "orders"),
    ("order_items", "product_id", "products"),
)

EXPECTED_COUNTS = {
    "brands": (8, 10),
    "categories": (8, 10),
    "vendors": (8, 10),
    "products": (40, 50),
    "customers": (20, 30),
    "orders": (30, 50),
    "order_items": (60, 150),
}

UNIQUE_COLUMNS = {
    "brands": ("name",),
    "categories": ("name",),
    "vendors": ("name",),
    "products": ("name",),
    "customers": ("email",),
}

ORDER_STATUSES = {"Processing", "Shipped", "Delivered", "Cancelled"}
PAYMENT_METHODS = {"UPI", "Credit Card", "Debit Card", "Net Banking", "Cash on Delivery"}
MAX_QUANTITY = 10

BANANA = "banana"
EXPECTED_BANANA_COUNT = 5
_BANANA_WORD = re.compile(rf"\b{BANANA}\b", re.IGNORECASE)

Tables = dict[str, pd.DataFrame]


class DatasetError(Exception):
    pass


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BananaOccurrence:
    table: str
    row_id: str
    column: str
    value: str


def load_tables(data_dir: Path = DATA_DIR) -> Tables:
    tables: Tables = {}
    for name, spec in TABLES.items():
        path = data_dir / spec.file
        if not path.exists():
            raise DatasetError(f"missing file: {path}")
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        if tuple(frame.columns) != spec.columns:
            raise DatasetError(
                f"{spec.file}: expected columns {list(spec.columns)}, found {list(frame.columns)}"
            )
        tables[name] = frame
    return tables


def find_banana(tables: Tables) -> list[BananaOccurrence]:
    found = []
    for name, frame in tables.items():
        id_column = TABLES[name].id_column
        for _, row in frame.iterrows():
            for column in frame.columns:
                value = str(row[column])
                for _ in _BANANA_WORD.finditer(value):
                    found.append(BananaOccurrence(name, str(row[id_column]), column, value))
    return found


def check_required_values(tables: Tables) -> CheckResult:
    problems = []
    for name, frame in tables.items():
        spec = TABLES[name]
        for column in spec.columns:
            if column in spec.optional:
                continue
            blank = frame[frame[column].str.strip() == ""]
            for row_id in blank[spec.id_column]:
                problems.append(f"{spec.file}: {column} is empty (row {row_id or '?'})")
    return CheckResult("required values present", not problems, problems)


def check_unique_ids(tables: Tables) -> CheckResult:
    problems = []
    for name, frame in tables.items():
        spec = TABLES[name]
        dupes = frame[spec.id_column][frame[spec.id_column].duplicated()].unique()
        problems += [f"{spec.file}: duplicate {spec.id_column} {d}" for d in dupes]
        for column in UNIQUE_COLUMNS.get(name, ()):
            dupes = frame[column][frame[column].str.lower().duplicated()].unique()
            problems += [f"{spec.file}: duplicate {column} '{d}'" for d in dupes]
    return CheckResult("IDs and names unique", not problems, problems)


def check_foreign_keys(tables: Tables) -> CheckResult:
    problems = []
    for child, column, parent in FOREIGN_KEYS:
        known = set(tables[parent][TABLES[parent].id_column])
        child_frame = tables[child]
        broken = child_frame[~child_frame[column].isin(known)]
        for _, row in broken.iterrows():
            problems.append(
                f"{TABLES[child].file}: {row[TABLES[child].id_column]} has {column}="
                f"{row[column]}, which is not in {TABLES[parent].file}"
            )
    return CheckResult("references point to existing rows", not problems, problems)


def check_no_orphans(tables: Tables) -> CheckResult:
    problems = []
    for child, column, parent in FOREIGN_KEYS:
        referenced = set(tables[child][column])
        parent_ids = tables[parent][TABLES[parent].id_column]
        for orphan in parent_ids[~parent_ids.isin(referenced)]:
            problems.append(f"{TABLES[parent].file}: {orphan} is not used by any {child} row")
    return CheckResult("no orphan entities", not problems, problems)


def _positive_int(value: str) -> int | None:
    return int(value) if value.isdigit() and int(value) > 0 else None


def check_prices(tables: Tables) -> CheckResult:
    problems = []
    for _, row in tables["products"].iterrows():
        if _positive_int(row["price_inr"]) is None:
            problems.append(f"products.csv: {row['product_id']} price_inr '{row['price_inr']}'")
    return CheckResult("product prices are positive whole rupees", not problems, problems)


def check_order_items(tables: Tables) -> CheckResult:
    problems = []
    prices = dict(
        zip(tables["products"]["product_id"], tables["products"]["price_inr"], strict=True)
    )
    items = tables["order_items"]
    for _, row in items.iterrows():
        item = row["order_item_id"]
        quantity = _positive_int(row["quantity"])
        if quantity is None or quantity > MAX_QUANTITY:
            problems.append(
                f"order_items.csv: {item} quantity '{row['quantity']}' not 1-{MAX_QUANTITY}"
            )
        catalogue_price = prices.get(row["product_id"])
        if catalogue_price is not None and row["unit_price_inr"] != catalogue_price:
            problems.append(
                f"order_items.csv: {item} unit_price_inr {row['unit_price_inr']} != "
                f"{row['product_id']} price_inr {catalogue_price}"
            )
    repeated = items[items.duplicated(["order_id", "product_id"], keep=False)]
    for (order, product), _ in repeated.groupby(["order_id", "product_id"]):
        problems.append(f"order_items.csv: {product} appears twice in {order}; use quantity")
    return CheckResult("order items: valid quantities and catalogue prices", not problems, problems)


def check_orders(tables: Tables, today: date | None = None) -> CheckResult:
    today = today or date.today()
    problems = []
    for _, row in tables["orders"].iterrows():
        order = row["order_id"]
        try:
            placed = date.fromisoformat(row["order_date"])
            if placed > today:
                problems.append(f"orders.csv: {order} order_date {placed} is in the future")
        except ValueError:
            problems.append(
                f"orders.csv: {order} order_date '{row['order_date']}' is not YYYY-MM-DD"
            )
        if row["status"] not in ORDER_STATUSES:
            problems.append(f"orders.csv: {order} status '{row['status']}'")
        if row["payment_method"] not in PAYMENT_METHODS:
            problems.append(f"orders.csv: {order} payment_method '{row['payment_method']}'")
    return CheckResult("orders: valid dates, statuses and payment methods", not problems, problems)


def check_counts(tables: Tables) -> CheckResult:
    problems = []
    for name, (low, high) in EXPECTED_COUNTS.items():
        count = len(tables[name])
        if not low <= count <= high:
            problems.append(f"{TABLES[name].file}: {count} rows, expected {low}-{high}")
    return CheckResult("entity counts in expected ranges", not problems, problems)


def check_banana(tables: Tables) -> CheckResult:
    found = find_banana(tables)
    problems = []
    if len(found) != EXPECTED_BANANA_COUNT:
        problems.append(
            f"found {len(found)} occurrences of '{BANANA}', expected {EXPECTED_BANANA_COUNT}"
        )
    for hit in found:
        literal = [m.group(0) for m in _BANANA_WORD.finditer(hit.value)]
        if any(word != BANANA for word in literal):
            problems.append(f"{hit.table} {hit.row_id}.{hit.column}: not lowercase: '{hit.value}'")
    return CheckResult(f"exactly {EXPECTED_BANANA_COUNT} x '{BANANA}'", not problems, problems)


def validate(tables: Tables, today: date | None = None) -> list[CheckResult]:
    return [
        check_required_values(tables),
        check_unique_ids(tables),
        check_foreign_keys(tables),
        check_no_orphans(tables),
        check_prices(tables),
        check_order_items(tables),
        check_orders(tables, today),
        check_counts(tables),
        check_banana(tables),
    ]
