"""
executor.py
───────────
Safe, read-only SQL execution against the Chinook SQLite database.

Provides `execute_sql(sql_query)` which:
  1. Validates the query is read-only (rejects write/DDL statements).
  2. Applies basic SQL-injection heuristics.
  3. Opens the database in read-only mode (SQLite URI).
  4. Returns results as a JSON-serialisable list of dicts.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from dataclasses import dataclass
from typing import Any


# ── Configuration ───────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = Path(
    os.getenv("DATABASE_PATH", str(BASE_DIR / "sample_db" / "chinook.db"))
)
DEFAULT_ROW_LIMIT = 100


# ── Blocked patterns ───────────────────────────────────────────────────

# Statements that modify data or schema — matched at word boundaries,
# case-insensitive, against the full query text.
_WRITE_KEYWORDS: list[str] = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "REPLACE", "TRUNCATE", "RENAME", "ATTACH", "DETACH",
    "REINDEX", "VACUUM", "ANALYZE",
]

_WRITE_PATTERN = re.compile(
    r"\b(" + "|".join(_WRITE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# ── SQL-injection heuristics ────────────────────────────────────────────
# These catch the most common attack vectors.  They are intentionally
# conservative (may reject some exotic-but-valid queries).

_INJECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Stacked queries: semicolons followed by another statement
    (
        re.compile(r";\s*\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH)\b", re.IGNORECASE),
        "Multiple statements (stacked queries) are not allowed.",
    ),
    # Comment-based obfuscation
    (
        re.compile(r"(--|/\*|#)"),
        "SQL comments are not allowed in queries.",
    ),
    # UNION-based injection (UNION followed by SELECT)
    (
        re.compile(r"\bUNION\b\s+\bALL\b\s+\bSELECT\b|\bUNION\b\s+\bSELECT\b", re.IGNORECASE),
        "UNION SELECT is not allowed for security reasons.",
    ),
    # Hex / char obfuscation (e.g. CHAR(0x41))
    (
        re.compile(r"\bCHAR\s*\(", re.IGNORECASE),
        "CHAR() function is not allowed.",
    ),
    # load_extension attack
    (
        re.compile(r"\bload_extension\b", re.IGNORECASE),
        "load_extension is not allowed.",
    ),
    # Writing to files via INTO OUTFILE / INTO DUMPFILE (MySQL-isms,
    # but block anyway for defence in depth).
    (
        re.compile(r"\bINTO\s+(OUTFILE|DUMPFILE)\b", re.IGNORECASE),
        "File-writing clauses are not allowed.",
    ),
]


# ── Exceptions ──────────────────────────────────────────────────────────

class ReadOnlyViolation(Exception):
    """Raised when a query attempts a write operation."""


class SQLInjectionSuspected(Exception):
    """Raised when a query matches an injection heuristic."""


class QueryExecutionError(Exception):
    """Raised when SQLite fails to execute the query."""


# ── Result container ────────────────────────────────────────────────────

@dataclass
class QueryResult:
    """Structured result from execute_sql()."""
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool  # True if results were capped by the row limit

    def to_json(self, **kwargs) -> str:
        """Serialise the result to a JSON string."""
        return json.dumps(
            {
                "sql": self.sql,
                "columns": self.columns,
                "rows": self.rows,
                "row_count": self.row_count,
                "truncated": self.truncated,
            },
            default=str,   # handles dates, Decimals, etc.
            **kwargs,
        )


# ── Core function ───────────────────────────────────────────────────────

def execute_sql(
    sql_query: str,
    *,
    db_path: str | Path | None = None,
    limit: int = DEFAULT_ROW_LIMIT,
) -> QueryResult:
    """
    Execute a **read-only** SQL query against the Chinook database.

    Parameters
    ----------
    sql_query
        The SQL query to execute.  Must be a single SELECT statement.
    db_path
        Path to the SQLite database.  Defaults to ``sample_db/chinook.db``.
    limit
        Maximum number of rows to return.  Defaults to 100.

    Returns
    -------
    QueryResult
        A structured object with columns, rows (list of dicts),
        row_count, and a ``to_json()`` helper.

    Raises
    ------
    ReadOnlyViolation
        If the query contains write/DDL keywords.
    SQLInjectionSuspected
        If the query matches an injection heuristic.
    QueryExecutionError
        If SQLite returns an error during execution.
    """
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    sql_clean = sql_query.strip().rstrip(";")

    # ── Guard 1: reject empty queries ────────────────────────────────
    if not sql_clean:
        raise QueryExecutionError("Empty query.")

    # ── Guard 2: must start with SELECT (or WITH for CTEs) ───────────
    first_word = sql_clean.split()[0].upper()
    if first_word not in ("SELECT", "WITH", "EXPLAIN"):
        raise ReadOnlyViolation(
            f"Only SELECT queries are allowed. Got: {first_word}"
        )

    # ── Guard 3: reject write / DDL keywords anywhere in the query ───
    match = _WRITE_PATTERN.search(sql_clean)
    if match:
        raise ReadOnlyViolation(
            f"Write operation \"{match.group(0).upper()}\" is not allowed."
        )

    # ── Guard 4: SQL-injection heuristics ────────────────────────────
    for pattern, message in _INJECTION_PATTERNS:
        if pattern.search(sql_clean):
            raise SQLInjectionSuspected(message)

    # ── Execute in read-only mode ────────────────────────────────────
    # SQLite URI mode with ?mode=ro makes the connection truly read-only
    # at the engine level — an extra safety net beyond our keyword checks.
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.cursor()
        cursor.execute(sql_clean)

        # Fetch up to limit+1 rows to detect truncation.
        raw_rows = cursor.fetchmany(limit + 1)
        truncated = len(raw_rows) > limit
        if truncated:
            raw_rows = raw_rows[:limit]

        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = [dict(row) for row in raw_rows]

    except sqlite3.Error as exc:
        raise QueryExecutionError(f"SQLite error: {exc}") from exc
    finally:
        conn.close()

    return QueryResult(
        sql=sql_query,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
    )


# ── Quick self-test ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # ── Happy-path tests ─────────────────────────────────────────────
    print("=== Valid SELECT ===")
    result = execute_sql("SELECT Name FROM Artist LIMIT 5")
    print(result.to_json(indent=2))
    print()

    # ── Security tests ───────────────────────────────────────────────
    attack_queries = [
        ("DROP TABLE Artist",                     ReadOnlyViolation),
        ("DELETE FROM Artist WHERE 1=1",          ReadOnlyViolation),
        ("INSERT INTO Artist VALUES (999,'X')",   ReadOnlyViolation),
        ("UPDATE Artist SET Name='X'",            ReadOnlyViolation),
        ("SELECT 1; DROP TABLE Artist",           ReadOnlyViolation),
        ("SELECT * FROM Artist -- WHERE 1=1",     SQLInjectionSuspected),
        ("SELECT * FROM Artist /* comment */",     SQLInjectionSuspected),
    ]

    all_ok = True
    for query, expected_exc in attack_queries:
        try:
            execute_sql(query)
            print(f"  FAIL  {query!r} — should have raised {expected_exc.__name__}")
            all_ok = False
        except expected_exc as e:
            print(f"  PASS  {query!r} -> {e}")
        except Exception as e:
            print(f"  FAIL  {query!r} — got {type(e).__name__}: {e}")
            all_ok = False

    print()
    print("All security checks passed!" if all_ok else "SOME CHECKS FAILED!")
    sys.exit(0 if all_ok else 1)
