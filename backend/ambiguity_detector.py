"""
ambiguity_detector.py
─────────────────────
Pre-LLM heuristic check that flags natural-language questions as
ambiguous *before* sending them to the model.

Detects three categories of ambiguity:
  (a) Vague superlatives  – "top", "best", "most" without a clear metric.
  (b) Unresolved time refs – "recent", "last quarter" with no date range.
  (c) Entity collisions   – a word maps to multiple tables or columns
                             in the Chinook schema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ── (a) Vague superlatives ──────────────────────────────────────────────

# Superlative keywords that need a measurable metric to be unambiguous.
_SUPERLATIVE_KEYWORDS: list[str] = [
    "top", "best", "worst", "most", "least", "highest", "lowest",
    "biggest", "smallest", "largest", "greatest", "fastest", "slowest",
]

# If any of these metric-like words appear near the superlative, the
# question is probably specific enough (e.g. "top 5 by revenue").
_METRIC_HINTS: list[str] = [
    "revenue", "sales", "total", "count", "price", "quantity", "amount",
    "duration", "length", "size", "bytes", "milliseconds", "tracks",
    "albums", "invoices", "customers", "employees", "orders",
    "unit price", "unitprice", "earning",
]


def _check_vague_superlatives(question_lower: str) -> str | None:
    """Return a reason string if the question uses a superlative without
    an accompanying metric; otherwise return None."""

    for keyword in _SUPERLATIVE_KEYWORDS:
        # Match the keyword as a whole word.
        if not re.search(rf"\b{keyword}\b", question_lower):
            continue

        # Check whether a metric hint is also present.
        has_metric = any(m in question_lower for m in _METRIC_HINTS)

        # Also accept patterns like "top 5 genres" — a number + noun is
        # usually specific enough context.
        has_number_context = bool(
            re.search(rf"\b{keyword}\s+\d+\s+\w+", question_lower)
        )

        if not has_metric and not has_number_context:
            return (
                f"The question uses \"{keyword}\" without specifying a "
                f"metric (e.g. by revenue, by count, by total sales). "
                f"Please clarify what \"{keyword}\" should be measured by."
            )

    return None


# ── (b) Unresolved time references ─────────────────────────────────────

_TIME_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"\b(recent|recently|latest)\b"),
        "The question mentions \"{match}\" but does not specify a date "
        "range. Please clarify (e.g. last 30 days, since 2024-01-01).",
    ),
    (
        re.compile(r"\blast\s+(week|month|quarter|year|half)\b"),
        "The question mentions \"{match}\" without an explicit date "
        "range. Which calendar period do you mean?",
    ),
    (
        re.compile(r"\b(this\s+(?:week|month|quarter|year))\b"),
        "The question mentions \"{match}\" — please confirm or provide "
        "an explicit start/end date.",
    ),
    (
        re.compile(r"\b(past\s+(?:few|couple|several)?\s*(?:days|weeks|months|years))\b"),
        "The question mentions \"{match}\" which is vague. Please "
        "specify an exact number of days/months.",
    ),
]


def _check_time_ambiguity(question_lower: str) -> str | None:
    """Return a reason string if the question has an unresolved time
    reference; otherwise return None."""

    # If the question already contains a concrete date (ISO-style or
    # common formats), skip the check.
    if re.search(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b", question_lower):
        return None
    if re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2},?\s+\d{4}\b", question_lower):
        return None

    for pattern, template in _TIME_PATTERNS:
        match = pattern.search(question_lower)
        if match:
            return template.format(match=match.group(0))

    return None


# ── (c) Entity collisions ──────────────────────────────────────────────

def _extract_schema_names(schema_description: str) -> dict[str, list[str]]:
    """
    Parse the DDL string and return a mapping of
    lowercased_name → list of qualified locations
    (e.g. {"name": ["Artist.Name", "Genre.Name", "Track.Name", ...]}).

    This lets us detect when a user's word matches columns/tables in
    more than one place.
    """
    name_map: dict[str, list[str]] = {}

    current_table: str | None = None
    for line in schema_description.splitlines():
        # Match "CREATE TABLE <TableName> ("
        table_match = re.match(r"CREATE\s+TABLE\s+(\w+)\s*\(", line, re.IGNORECASE)
        if table_match:
            current_table = table_match.group(1)
            # Register the table name itself.
            key = current_table.lower()
            name_map.setdefault(key, []).append(current_table)
            continue

        # Match column definitions: "  ColumnName TYPE ..."
        if current_table:
            col_match = re.match(r"\s+(\w+)\s+\w+", line)
            if col_match:
                col_name = col_match.group(1)
                key = col_name.lower()
                name_map.setdefault(key, []).append(f"{current_table}.{col_name}")

    return name_map


# Words that are too common / generic to count as collisions.
_IGNORE_WORDS: set[str] = {
    "id", "the", "a", "an", "in", "of", "for", "and", "or",
    "is", "are", "was", "were", "how", "many", "much", "what", "which",
    "who", "where", "when", "show", "list", "get", "find", "give",
    "all", "each", "every", "by", "from", "to", "with", "on", "at",
    "it", "its", "do", "does", "did", "has", "have", "had", "not",
    "no", "yes", "me", "my", "i", "we", "you", "they", "them",
    "total", "count", "number", "average", "sum",
}


def _check_entity_collisions(
    question_lower: str,
    schema_description: str,
) -> str | None:
    """Return a reason string if a word in the question matches
    columns/tables in multiple places; otherwise return None."""

    name_map = _extract_schema_names(schema_description)

    # Tokenise the question into words.
    words = set(re.findall(r"[a-z]+", question_lower))
    words -= _IGNORE_WORDS

    collisions: list[str] = []

    for word in words:
        locations = name_map.get(word, [])
        if len(locations) > 1:
            collisions.append(
                f"\"{word}\" matches multiple schema locations: "
                + ", ".join(locations)
            )

    if collisions:
        return (
            "The question contains terms that map to multiple tables or "
            "columns in the database. " + "; ".join(collisions) + ". "
            "Please specify which one you mean."
        )

    return None


# ── Public API ──────────────────────────────────────────────────────────

@dataclass
class AmbiguityResult:
    """Result of the ambiguity check."""
    is_ambiguous: bool
    reason: str  # empty string when not ambiguous


def is_ambiguous(question: str, schema_description: str) -> AmbiguityResult:
    """
    Check whether *question* is ambiguous given the Chinook
    *schema_description* (DDL string).

    Returns an `AmbiguityResult` with `is_ambiguous=True` and a
    human-readable `reason` when any ambiguity is detected.

    Detection categories
    --------------------
    (a) Vague superlatives without a metric.
    (b) Time-related words without an explicit date range.
    (c) Entity names that match multiple tables/columns.
    """
    q = question.lower().strip()
    reasons: list[str] = []

    # (a) Vague superlatives
    reason_a = _check_vague_superlatives(q)
    if reason_a:
        reasons.append(reason_a)

    # (b) Unresolved time references
    reason_b = _check_time_ambiguity(q)
    if reason_b:
        reasons.append(reason_b)

    # (c) Entity collisions with schema
    reason_c = _check_entity_collisions(q, schema_description)
    if reason_c:
        reasons.append(reason_c)

    if reasons:
        return AmbiguityResult(is_ambiguous=True, reason=" | ".join(reasons))

    return AmbiguityResult(is_ambiguous=False, reason="")


# ── Quick self-test ─────────────────────────────────────────────────────

if __name__ == "__main__":
    sample_ddl = """\
CREATE TABLE Artist (
  ArtistId INTEGER PRIMARY KEY NOT NULL,
  Name NVARCHAR(120)
);

CREATE TABLE Album (
  AlbumId INTEGER PRIMARY KEY NOT NULL,
  Title NVARCHAR(160) NOT NULL,
  ArtistId INTEGER NOT NULL REFERENCES Artist.ArtistId
);

CREATE TABLE Track (
  TrackId INTEGER PRIMARY KEY NOT NULL,
  Name NVARCHAR(200) NOT NULL,
  AlbumId INTEGER REFERENCES Album.AlbumId,
  GenreId INTEGER REFERENCES Genre.GenreId,
  Composer NVARCHAR(220),
  Milliseconds INTEGER NOT NULL,
  Bytes INTEGER,
  UnitPrice NUMERIC(10,2) NOT NULL
);

CREATE TABLE Genre (
  GenreId INTEGER PRIMARY KEY NOT NULL,
  Name NVARCHAR(120)
);

CREATE TABLE Customer (
  CustomerId INTEGER PRIMARY KEY NOT NULL,
  FirstName NVARCHAR(40) NOT NULL,
  LastName NVARCHAR(20) NOT NULL,
  Email NVARCHAR(60) NOT NULL
);
"""

    test_cases = [
        "Show me the top artists",
        "What were the most recent purchases?",
        "Show me name details",
        "List the top 10 tracks by sales",
        "Show all genres",
        "What is the best album from last quarter?",
    ]

    for q in test_cases:
        result = is_ambiguous(q, sample_ddl)
        flag = "⚠ AMBIGUOUS" if result.is_ambiguous else "✓ CLEAR"
        print(f"{flag:14s}  │ {q}")
        if result.reason:
            print(f"{'':14s}  │   → {result.reason}")
        print()
