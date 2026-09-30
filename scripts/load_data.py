import argparse
import sys

import _bootstrap  # noqa: F401
from neo4j.exceptions import AuthError, ServiceUnavailable

from app.config import ConfigError, load_settings
from app.dataset import DatasetError, load_tables, validate
from app.graph import Neo4jClient
from app.graph_checks import verify_graph
from app.loader import create_constraints, load_graph, reset_graph


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the dataset and load it into Neo4j.")
    parser.add_argument("--reset", action="store_true", help="delete all graph data first")
    args = parser.parse_args()

    try:
        tables = load_tables()
    except DatasetError as exc:
        print(f"Dataset unreadable: {exc}")
        return 1
    failed = [check for check in validate(tables) if not check.passed]
    if failed:
        print("Dataset validation failed; nothing was loaded:")
        for check in failed:
            print(f"  FAIL  {check.name}")
            for problem in check.problems:
                print(f"        - {problem}")
        return 1
    print("Dataset validation: all checks passed")

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(exc)
        return 1

    with Neo4jClient(settings) as client:
        try:
            client.verify_connectivity()
        except (ServiceUnavailable, AuthError) as exc:
            print(f"Cannot connect to Neo4j at {settings.neo4j_uri}: {str(exc).splitlines()[0]}")
            print("Is it running? Start it with: docker compose up -d --wait")
            return 1
        create_constraints(client)
        if args.reset:
            reset_graph(client)
            print("Graph reset: all nodes and relationships deleted")

        print(f"\n{'step':<12} {'rows':>5} {'nodes+':>7} {'rels+':>6} {'props set':>10}")
        for step in load_graph(client, tables):
            print(
                f"{step.step:<12} {step.rows:>5} {step.nodes_created:>7} "
                f"{step.relationships_created:>6} {step.properties_set:>10}"
            )

        print("\nGraph verification")
        results = verify_graph(client)
        for result in results:
            print(f"  {'PASS' if result.passed else 'FAIL'}  {result.name}")
            for problem in result.problems:
                print(f"        - {problem}")

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
