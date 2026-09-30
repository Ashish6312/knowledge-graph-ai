import sys

import _bootstrap  # noqa: F401

from app.config import load_settings
from app.graph import Neo4jClient
from app.graph_checks import (
    EXPECTED_NODES,
    EXPECTED_RELATIONSHIPS,
    node_counts,
    relationship_counts,
    verify_graph,
)


def main() -> int:
    with Neo4jClient(load_settings()) as client:
        nodes = node_counts(client)
        relationships = relationship_counts(client)

        print(f"{'node label':<14} {'found':>6} {'expected':>9}")
        for label, expected in EXPECTED_NODES.items():
            print(f"{label:<14} {nodes.get(label, 0):>6} {expected:>9}")
        print(f"{'TOTAL':<14} {sum(nodes.values()):>6} {sum(EXPECTED_NODES.values()):>9}")

        print(f"\n{'relationship':<14} {'found':>6} {'expected':>9}")
        for rel, expected in EXPECTED_RELATIONSHIPS.items():
            print(f"{rel:<14} {relationships.get(rel, 0):>6} {expected:>9}")
        print(
            f"{'TOTAL':<14} {sum(relationships.values()):>6} "
            f"{sum(EXPECTED_RELATIONSHIPS.values()):>9}"
        )

        print("\nChecks")
        results = verify_graph(client)
        for result in results:
            print(f"  {'PASS' if result.passed else 'FAIL'}  {result.name}")
            for problem in result.problems:
                print(f"        - {problem}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
