"""
main.py
───────
FastAPI application for the text-to-sql-clarify service.

Endpoints
---------
GET  /health            → health check
GET  /schema            → return the database schema
POST /query             → NL question → ambiguity check → SQL or clarifying question
POST /query/resolve     → original question + user's answer → refined question → SQL
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.schema_loader import load_schema, DatabaseSchema
from backend.sql_generator import (
    generate_sql, generate_sql_best_guess,
    ClarifyResult, SQLResult,
)
from backend.executor import (
    execute_sql, ReadOnlyViolation, SQLInjectionSuspected, QueryExecutionError,
)
from backend.ambiguity_detector import is_ambiguous
from backend.clarifier import generate_clarifying_question

# ── App setup ───────────────────────────────────────────────────────────

app = FastAPI(
    title="Text-to-SQL Clarify",
    description="Natural-language to SQL with ambiguity detection and clarification",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Database & schema ──────────────────────────────────────────────────

DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "sample_db" / "chinook.db")))

_schema_cache: DatabaseSchema | None = None
_ddl_cache: str | None = None


def _get_schema() -> DatabaseSchema:
    """Load and cache the DatabaseSchema object."""
    global _schema_cache
    if _schema_cache is None:
        if not DB_PATH.exists():
            raise HTTPException(status_code=500, detail=f"Database not found at {DB_PATH}")
        _schema_cache = load_schema(DB_PATH)
    return _schema_cache


def _get_ddl() -> str:
    """Return the cached DDL string."""
    global _ddl_cache
    if _ddl_cache is None:
        _ddl_cache = _get_schema().to_ddl()
    return _ddl_cache


# ── Shared helper: run generate_sql → execute → build response ────────

def _sql_pipeline(question: str, ddl: str) -> QueryResponse:
    """
    Call the LLM to generate SQL from *question*, execute the query
    via executor.py, and return a QueryResponse.
    """
    try:
        result = generate_sql(question, ddl)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")

    # The LLM itself may still ask to clarify (separate from our
    # heuristic detector). Surface that transparently.
    if isinstance(result, ClarifyResult):
        return QueryResponse(
            action="clarify",
            clarifying_question="; ".join(result.questions),
            original_question=question,
        )

    if isinstance(result, SQLResult):
        if result.error:
            return QueryResponse(action="error", error=result.error)

        try:
            qr = execute_sql(result.sql, db_path=DB_PATH)
        except (ReadOnlyViolation, SQLInjectionSuspected) as exc:
            return QueryResponse(
                action="error",
                sql=result.sql,
                explanation=result.explanation,
                error=f"Query blocked: {exc}",
            )
        except (QueryExecutionError, FileNotFoundError) as exc:
            return QueryResponse(
                action="error",
                sql=result.sql,
                explanation=result.explanation,
                error=str(exc),
            )

        return QueryResponse(
            action="sql",
            sql=result.sql,
            explanation=result.explanation,
            results=qr.rows,
        )

    raise HTTPException(status_code=500, detail="Unexpected result type")


def _best_guess_pipeline(question: str, ddl: str) -> QueryResponse:
    """
    Call the LLM in best-guess mode: never clarify, always generate SQL,
    and report any assumptions made.  Executes via executor.py.
    """
    try:
        result = generate_sql_best_guess(question, ddl)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")

    if result.error:
        return QueryResponse(action="error", error=result.error)

    try:
        qr = execute_sql(result.sql, db_path=DB_PATH)
    except (ReadOnlyViolation, SQLInjectionSuspected) as exc:
        return QueryResponse(
            action="error",
            sql=result.sql,
            explanation=result.explanation,
            error=f"Query blocked: {exc}",
        )
    except (QueryExecutionError, FileNotFoundError) as exc:
        return QueryResponse(
            action="error",
            sql=result.sql,
            explanation=result.explanation,
            error=str(exc),
        )

    return QueryResponse(
        action="sql",
        sql=result.sql,
        explanation=result.explanation,
        results=qr.rows,
        assumption_made=result.assumption_made,
    )


# ── Request / Response models ──────────────────────────────────────────

class QueryRequest(BaseModel):
    """Payload for POST /query."""
    question: str = Field(..., min_length=1, description="Natural-language question")
    clarification_enabled: bool = Field(
        True,
        description=(
            "When True (default), ambiguous questions trigger a "
            "clarifying question. When False, the LLM makes its best "
            "guess and reports what it assumed."
        ),
    )


class ResolveRequest(BaseModel):
    """Payload for POST /query/resolve."""
    original_question: str = Field(
        ..., min_length=1,
        description="The original question that was flagged as ambiguous",
    )
    clarification_answer: str = Field(
        ..., min_length=1,
        description="The user's answer to the clarifying question",
    )


class QueryResponse(BaseModel):
    """Unified response for /query and /query/resolve."""
    action: str                                       # "sql" | "clarify" | "error"
    sql: Optional[str] = None                         # generated SQL
    explanation: Optional[str] = None                 # plain-english explanation
    results: Optional[list[dict]] = None              # query result rows
    clarifying_question: Optional[str] = None         # follow-up question for the user
    original_question: Optional[str] = None           # echoed back so /resolve can use it
    ambiguity_reason: Optional[str] = None            # raw reason from the detector
    assumption_made: Optional[str] = None             # what the LLM assumed (best-guess mode)
    error: Optional[str] = None                       # error message


class SchemaResponse(BaseModel):
    """Response for GET /schema."""
    db_path: str
    tables: list[str]
    ddl: str
    summary: str


# ── Endpoints ───────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


@app.get("/schema", response_model=SchemaResponse)
async def get_schema():
    """Return the introspected Chinook database schema."""
    schema = _get_schema()
    return SchemaResponse(
        db_path=schema.db_path,
        tables=schema.table_names(),
        ddl=schema.to_ddl(),
        summary=schema.summary(),
    )


@app.post("/query", response_model=QueryResponse)
async def query(body: QueryRequest):
    """
    Accept a natural-language question about the Chinook database.

    **clarification_enabled=True** (default):
    Runs the heuristic ambiguity detector first.  If ambiguous, returns
    a clarifying question (``action="clarify"``).  Otherwise generates
    SQL and executes it.

    **clarification_enabled=False**:
    Skips ambiguity detection entirely.  The LLM makes its best-guess
    assumptions (e.g. "top" → by total revenue) and always returns SQL.
    A short ``assumption_made`` string describes what it silently guessed.
    """
    ddl = _get_ddl()

    # ── Fast path: best-guess mode (no clarification) ────────────────
    if not body.clarification_enabled:
        return _best_guess_pipeline(body.question, ddl)

    # ── Step 1: heuristic ambiguity check ────────────────────────────
    ambiguity = is_ambiguous(body.question, ddl)

    if ambiguity.is_ambiguous:
        try:
            follow_up = generate_clarifying_question(
                body.question, ambiguity.reason, ddl,
            )
        except Exception as exc:
            # If the clarifier LLM call fails, fall back to the raw
            # reason so the user still gets something useful.
            follow_up = ambiguity.reason

        return QueryResponse(
            action="clarify",
            clarifying_question=follow_up,
            original_question=body.question,
            ambiguity_reason=ambiguity.reason,
        )

    # ── Step 2: question is clear → generate SQL ─────────────────────
    return _sql_pipeline(body.question, ddl)


@app.post("/query/resolve", response_model=QueryResponse)
async def query_resolve(body: ResolveRequest):
    """
    Resolve an ambiguous question.

    The client sends back the ``original_question`` (from the prior
    ``/query`` response) together with the user's
    ``clarification_answer``.  This endpoint merges them into a single
    refined question and passes it to ``generate_sql()``.

    Example
    -------
    ```json
    {
      "original_question": "Show me the top artists",
      "clarification_answer": "By total revenue"
    }
    ```
    → refined question: *"Show me the top artists. By total revenue"*
    → SQL generation + execution.
    """
    ddl = _get_ddl()

    # Merge the original question with the user's clarification into a
    # single, refined prompt for the LLM.
    refined = f"{body.original_question.rstrip('?.')}. {body.clarification_answer}"

    return _sql_pipeline(refined, ddl)


# ── Frontend serving ───────────────────────────────────────────────────

FRONTEND_DIR = BASE_DIR / "frontend"


@app.get("/", include_in_schema=False)
async def serve_frontend():
    """Serve the frontend single-page application."""
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(str(index))


# Mount static assets (CSS, JS, images if added later).
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
