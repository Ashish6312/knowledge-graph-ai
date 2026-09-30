import sys

import _bootstrap  # noqa: F401

from app.config import load_settings
from app.example_queries import EXAMPLES
from app.graph import Neo4jClient

MAX_ROWS_SHOWN = 12


def main() -> int:
    wanted = {int(arg) for arg in sys.argv[1:]}
    with Neo4jClient(load_settings()) as client:
        for query in EXAMPLES:
            if wanted and query.number not in wanted:
                continue
            rows = client.read(query.cypher, **query.params)
            print(f"=== Query {query.number}: {query.question}")
            print(query.cypher.strip())
            if query.params:
                print(f"params: {query.params}")
            print(f"--- {len(rows)} row(s)")
            for row in rows[:MAX_ROWS_SHOWN]:
                print(f"  {row}")
            if len(rows) > MAX_ROWS_SHOWN:
                print(f"  ... {len(rows) - MAX_ROWS_SHOWN} more")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
