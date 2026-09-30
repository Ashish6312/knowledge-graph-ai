from types import TracebackType
from typing import Any, LiteralString, Self

from neo4j import (
    READ_ACCESS,
    Driver,
    GraphDatabase,
    ManagedTransaction,
    Query,
    Record,
    RoutingControl,
    SummaryCounters,
    unit_of_work,
)

from app.config import Settings


class Neo4jClient:
    def __init__(self, settings: Settings) -> None:
        self._driver: Driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
        )
        self._database = settings.neo4j_database
        self._timeout = settings.query_timeout_seconds

    def verify_connectivity(self) -> None:
        self._driver.verify_connectivity()

    def read(self, cypher: LiteralString, **params: Any) -> list[dict[str, Any]]:
        records, _, _ = self._driver.execute_query(
            Query(cypher, timeout=self._timeout),
            params,
            database_=self._database,
            routing_=RoutingControl.READ,
        )
        return [record.data() for record in records]

    def query_type(self, cypher: LiteralString) -> str:
        with self._driver.session(database=self._database) as session:
            summary = session.run(Query("EXPLAIN " + cypher, timeout=self._timeout)).consume()
        return str(summary.query_type)

    def read_only(self, cypher: LiteralString, max_rows: int) -> tuple[list[dict[str, Any]], bool]:
        @unit_of_work(timeout=self._timeout)
        def work(tx: ManagedTransaction) -> list[Record]:
            return tx.run(cypher).fetch(max_rows + 1)

        with self._driver.session(
            database=self._database, default_access_mode=READ_ACCESS
        ) as session:
            records = session.execute_read(work)
        return [record.data() for record in records[:max_rows]], len(records) > max_rows

    def write(self, cypher: LiteralString, **params: Any) -> SummaryCounters:
        _, summary, _ = self._driver.execute_query(
            Query(cypher, timeout=self._timeout),
            params,
            database_=self._database,
            routing_=RoutingControl.WRITE,
        )
        return summary.counters

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
