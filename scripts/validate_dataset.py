import sys

import _bootstrap  # noqa: F401

from app.dataset import TABLES, DatasetError, find_banana, load_tables, validate


def main() -> int:
    try:
        tables = load_tables()
    except DatasetError as exc:
        print(f"FAIL  cannot read dataset: {exc}")
        return 1

    print("Row counts")
    for name, frame in tables.items():
        print(f"  {TABLES[name].file:<18} {len(frame):>4}")

    print("\nChecks")
    results = validate(tables)
    for result in results:
        print(f"  {'PASS' if result.passed else 'FAIL'}  {result.name}")
        for problem in result.problems:
            print(f"        - {problem}")

    print("\nbanana occurrences")
    for hit in find_banana(tables):
        print(f"  {TABLES[hit.table].file:<15} {hit.row_id:<7} {hit.column:<14} {hit.value}")

    failed = [r for r in results if not r.passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
