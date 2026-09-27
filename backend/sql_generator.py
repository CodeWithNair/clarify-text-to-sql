"""
sql_generator.py
────────────────
Takes a natural-language question and a schema description string,
then calls the Groq API to generate a valid SQL query for the Chinook
database — or asks clarifying questions when the intent is ambiguous.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from groq import Groq


# ── Configuration ───────────────────────────────────────────────────────

DEFAULT_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")

SYSTEM_PROMPT = """\
You are a SQL expert for the Chinook music-store database (SQLite).

You will receive:
1. The full database schema (DDL with primary keys, foreign keys, types).
2. A natural-language question from the user.

Decide ONE of two actions and respond with **only** a JSON object:

**Action A – Clarify** (question is ambiguous / under-specified):
{
  "action": "clarify",
  "questions": ["<clarifying question 1>", "..."]
}

**Action B – Generate SQL** (question is clear enough):
{
  "action": "sql",
  "sql": "<valid SELECT query>",
  "explanation": "<one-line plain-english explanation>"
}

Rules:
- Return ONLY raw JSON. No markdown fences, no extra text.
- Only SELECT queries. Never INSERT / UPDATE / DELETE / DROP.
- Use table and column names EXACTLY as shown in the schema.
- Prefer explicit JOINs over implicit comma-joins.
- Qualify ambiguous column names with their table name.
"""


# ── Result types ────────────────────────────────────────────────────────

@dataclass
class ClarifyResult:
    """The model needs more information before it can write SQL."""
    questions: list[str]


@dataclass
class SQLResult:
    """The model generated a SQL query."""
    sql: str
    explanation: str
    error: Optional[str] = None
    assumption_made: Optional[str] = None


# ── Core function ───────────────────────────────────────────────────────

def generate_sql(
    question: str,
    schema_description: str,
    *,
    conversation_history: list[dict] | None = None,
    model: str = DEFAULT_MODEL,
) -> ClarifyResult | SQLResult:
    """
    Call the Groq LLM with the Chinook *schema_description* (DDL string)
    and the user's natural-language *question*.

    Parameters
    ----------
    question
        Natural-language question (e.g. "top 5 genres by track count").
    schema_description
        Plain-text DDL string describing the database schema.
    conversation_history
        Optional prior chat messages for multi-turn clarification.
    model
        Groq model identifier.

    Returns
    -------
    ClarifyResult  – if the model asks for clarification.
    SQLResult      – if the model generates SQL (or encounters an error).
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"## Database Schema\n\n```sql\n{schema_description}\n```",
        },
    ]

    if conversation_history:
        messages.extend(conversation_history)

    messages.append({"role": "user", "content": question})

    # ── Call Groq ────────────────────────────────────────────────────────
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=1024,
    )

    raw = response.choices[0].message.content.strip()

    # ── Parse JSON response ─────────────────────────────────────────────
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Model sometimes wraps JSON in markdown fences; try to extract.
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
        else:
            return SQLResult(
                sql="", explanation="",
                error=f"Unparseable LLM response:\n{raw}",
            )

    action = data.get("action")

    if action == "clarify":
        return ClarifyResult(questions=data.get("questions", []))

    if action == "sql":
        return SQLResult(
            sql=data.get("sql", ""),
            explanation=data.get("explanation", ""),
        )

    return SQLResult(sql="", explanation="", error=f"Unexpected action: {action}")


# ── Query execution helper ──────────────────────────────────────────────

def execute_query(db_path: str | Path, sql: str, limit: int = 50) -> list[dict]:
    """
    Execute a read-only SQL query against a SQLite database.

    Returns at most *limit* rows as a list of dicts.
    Raises RuntimeError on failure.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        rows = [dict(row) for row in cursor.fetchmany(limit)]
    except Exception as exc:
        conn.close()
        raise RuntimeError(f"Query execution failed: {exc}") from exc
    conn.close()
    return rows


# ── Best-guess mode (no clarification) ──────────────────────────────────

BEST_GUESS_SYSTEM_PROMPT = """\
You are a SQL expert for the Chinook music-store database (SQLite).

You will receive:
1. The full database schema (DDL with primary keys, foreign keys, types).
2. A natural-language question from the user.

IMPORTANT: You must NEVER ask for clarification. Always generate a SQL
query, even if the question is vague or ambiguous. Make reasonable
default assumptions instead:

Default assumptions to apply when the question is vague:
- "top" / "best" / "most" without a metric → default to total revenue
  (SUM of InvoiceLine.UnitPrice * InvoiceLine.Quantity).
- "recent" / "latest" without a date range → ORDER BY date DESC LIMIT 10.
- Ambiguous entity names → pick the most commonly queried table
  (e.g. "name" → Artist.Name unless context suggests otherwise).
- No LIMIT specified → default to LIMIT 10.

Respond with **only** a JSON object:
{
  "action": "sql",
  "sql": "<valid SELECT query>",
  "explanation": "<one-line plain-english explanation>",
  "assumption_made": "<short description of any assumptions you made, or null if the question was unambiguous>"
}

Rules:
- Return ONLY raw JSON. No markdown fences, no extra text.
- Only SELECT queries. Never INSERT / UPDATE / DELETE / DROP.
- Use table and column names EXACTLY as shown in the schema.
- Prefer explicit JOINs over implicit comma-joins.
- Qualify ambiguous column names with their table name.
"""


def generate_sql_best_guess(
    question: str,
    schema_description: str,
    *,
    model: str = DEFAULT_MODEL,
) -> SQLResult:
    """
    Like ``generate_sql`` but **never** asks for clarification.

    The LLM is instructed to make reasonable default assumptions
    (e.g. "top" → by revenue) and report what it assumed via the
    ``assumption_made`` field of the returned ``SQLResult``.
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))

    messages: list[dict] = [
        {"role": "system", "content": BEST_GUESS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"## Database Schema\n\n```sql\n{schema_description}\n```",
        },
        {"role": "user", "content": question},
    ]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=1024,
    )

    raw = response.choices[0].message.content.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
        else:
            return SQLResult(
                sql="", explanation="",
                error=f"Unparseable LLM response:\n{raw}",
            )

    return SQLResult(
        sql=data.get("sql", ""),
        explanation=data.get("explanation", ""),
        assumption_made=data.get("assumption_made"),
    )

