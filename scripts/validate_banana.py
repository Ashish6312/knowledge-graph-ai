import sys

import _bootstrap  # noqa: F401

from app.config import load_settings
from app.dataset import EXPECTED_BANANA_COUNT
from app.graph import Neo4jClient
from app.graph_checks import banana_in_graph


def main() -> int:
    with Neo4jClient(load_settings()) as client:
        hits = banana_in_graph(client)

    total = sum(hit.occurrences for hit in hits)
    print(f"banana occurrences: {total}\n")
    for number, hit in enumerate(hits, start=1):
        print(f"{number}. {hit.label} {hit.entity_id} -> {hit.property}")
        print(f'   "{hit.value}"')

    ok = total == EXPECTED_BANANA_COUNT
    print(f"\n{'PASS' if ok else 'FAIL'}: expected {EXPECTED_BANANA_COUNT}, found {total}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
