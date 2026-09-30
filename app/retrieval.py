import re
from dataclasses import dataclass
from typing import Any, LiteralString

from app.graph import Neo4jClient

FORBIDDEN_KEYWORDS = (
    "CREATE", "MERGE", "DELETE", "DETACH", "SET", "REMOVE", "DROP", "LOAD", "FOREACH",
    "CALL", "USE", "ALTER", "GRANT", "DENY", "REVOKE", "START", "STOP", "TERMINATE",
    "SHOW", "FINISH",
)  # fmt: skip
_FORBIDDEN = re.compile(rf"\b({'|'.join(FORBIDDEN_KEYWORDS)})\b", re.IGNORECASE)
_READ_START = re.compile(r"^(MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|RETURN)\b", re.IGNORECASE)
_STRINGS = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
MAX_CYPHER_LENGTH = 2000


class UnsafeCypherError(Exception):
    pass


@dataclass(frozen=True)
class QueryResult:
    cypher: str
    rows: list[dict[str, Any]]
    truncated: bool


def check_cypher(cypher: str) -> str:
    query = cypher.strip().removesuffix(";").strip()
    if not query:
        raise UnsafeCypherError("the query is empty")
    if len(query) > MAX_CYPHER_LENGTH:
        raise UnsafeCypherError(f"the query is longer than {MAX_CYPHER_LENGTH} characters")

    code = _COMMENTS.sub(" ", _STRINGS.sub("''", query))
    if ";" in code:
        raise UnsafeCypherError("only one statement is allowed")
    if not _READ_START.match(code.strip()):
        raise UnsafeCypherError(
            "a read query must start with MATCH, OPTIONAL MATCH, WITH, UNWIND or RETURN"
        )
    found = sorted({word.upper() for word in _FORBIDDEN.findall(code)})
    if found:
        raise UnsafeCypherError(f"forbidden keyword(s): {', '.join(found)}")
    return query


def run_read_query(client: Neo4jClient, cypher: str, max_rows: int) -> QueryResult:
    query: LiteralString = check_cypher(cypher)  # pyright: ignore[reportAssignmentType]

    query_type = client.query_type(query)
    if query_type != "r":
        raise UnsafeCypherError(f"Neo4j classifies this query as '{query_type}', not read-only")

    rows, truncated = client.read_only(query, max_rows)
    return QueryResult(query, rows, truncated)
