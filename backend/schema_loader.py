"""
schema_loader.py
────────────────
Introspects a SQLite database and returns a structured representation
of its schema (tables, columns, types, primary/foreign keys).
This schema context is later fed to the LLM so it can generate valid SQL.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Column:
    """Represents a single column in a database table."""
    name: str
    data_type: str
    is_primary_key: bool = False
    is_nullable: bool = True
    default_value: Optional[str] = None
    foreign_key: Optional[str] = None  # e.g. "Artist.ArtistId"


@dataclass
class Table:
    """Represents a database table and its columns."""
    name: str
    columns: list[Column] = field(default_factory=list)


@dataclass
class DatabaseSchema:
    """Top-level container for the full database schema."""
    db_path: str
    tables: list[Table] = field(default_factory=list)

    # ── pretty-print helpers ────────────────────────────────────────────

    def to_ddl(self) -> str:
        """Return a compact DDL-style description suitable for LLM context."""
        lines: list[str] = []
        for table in self.tables:
            col_defs: list[str] = []
            for col in table.columns:
                parts = [f"  {col.name} {col.data_type}"]
                if col.is_primary_key:
                    parts.append("PRIMARY KEY")
                if not col.is_nullable:
                    parts.append("NOT NULL")
                if col.foreign_key:
                    parts.append(f"REFERENCES {col.foreign_key}")
                col_defs.append(" ".join(parts))
            lines.append(f"CREATE TABLE {table.name} (\n" + ",\n".join(col_defs) + "\n);\n")
        return "\n".join(lines)

    def table_names(self) -> list[str]:
        """Return a simple list of table names."""
        return [t.name for t in self.tables]

    def summary(self) -> str:
        """Return a human-readable summary of the schema."""
        parts: list[str] = [f"Database: {self.db_path}", f"Tables ({len(self.tables)}):"]
        for table in self.tables:
            pk_cols = [c.name for c in table.columns if c.is_primary_key]
            parts.append(f"  • {table.name}  ({len(table.columns)} cols, PK: {', '.join(pk_cols) or '—'})")
        return "\n".join(parts)


def load_schema(db_path: str | Path) -> DatabaseSchema:
    """
    Connect to the SQLite database at *db_path* and introspect its schema.

    Returns a fully-populated `DatabaseSchema` instance.
    """
    db_path = Path(db_path).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # ── discover tables ─────────────────────────────────────────────────
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    table_names = [row[0] for row in cursor.fetchall()]

    # ── build foreign-key lookup  (child_table.child_col → parent_table.parent_col)
    fk_map: dict[tuple[str, str], str] = {}
    for tname in table_names:
        cursor.execute(f"PRAGMA foreign_key_list([{tname}]);")
        for fk_row in cursor.fetchall():
            # fk_row: (id, seq, table, from, to, on_update, on_delete, match)
            parent_table = fk_row[2]
            child_col = fk_row[3]
            parent_col = fk_row[4]
            fk_map[(tname, child_col)] = f"{parent_table}.{parent_col}"

    # ── build Table / Column objects ────────────────────────────────────
    tables: list[Table] = []
    for tname in table_names:
        cursor.execute(f"PRAGMA table_info([{tname}]);")
        columns: list[Column] = []
        for col_row in cursor.fetchall():
            # col_row: (cid, name, type, notnull, dflt_value, pk)
            columns.append(
                Column(
                    name=col_row[1],
                    data_type=col_row[2] or "TEXT",
                    is_primary_key=bool(col_row[5]),
                    is_nullable=not bool(col_row[3]),
                    default_value=col_row[4],
                    foreign_key=fk_map.get((tname, col_row[1])),
                )
            )
        tables.append(Table(name=tname, columns=columns))

    conn.close()
    return DatabaseSchema(db_path=str(db_path), tables=tables)


# ── quick self-test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "sample_db/chinook.db"
    schema = load_schema(path)
    print(schema.summary())
    print()
    print(schema.to_ddl())
