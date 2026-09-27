"""
clarifier.py
────────────
Given a user question that was flagged as ambiguous, calls the Groq LLM
to produce ONE concise, natural-sounding clarifying question that
targets the specific ambiguity detected by ambiguity_detector.py.
"""

from __future__ import annotations

import os

from groq import Groq


DEFAULT_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")

SYSTEM_PROMPT = """\
You are a helpful data-analyst assistant for the Chinook music-store \
database (SQLite).

A user asked a question about the database, but an automated check \
flagged it as ambiguous.  You will receive:

1. The user's original question.
2. The specific ambiguity reason(s) detected.
3. The database schema (DDL).

Your task: write exactly ONE short, natural-sounding follow-up question \
that resolves the ambiguity.  The follow-up must:

- Be specific — offer concrete options drawn from the schema \
  (column names, table names, data types) so the user can just pick one.
- Sound conversational, not robotic.
- Be a single sentence (two at most).
- NOT repeat the original question verbatim.
- NOT include any SQL, code, or markdown.

Examples of good follow-ups:
• "Top by total revenue, number of tracks sold, or number of distinct albums?"
• "By 'recent' do you mean the last 30 days, last calendar year, or something else?"
• "'Name' could refer to artist name, track name, or genre name — which one?"

Respond with ONLY the follow-up question text.  No preamble, no quotes, \
no bullet points — just the question itself.
"""


def generate_clarifying_question(
    question: str,
    ambiguity_reason: str,
    schema_description: str,
    *,
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Call the Groq LLM to produce a single clarifying follow-up question.

    Parameters
    ----------
    question
        The user's original natural-language question.
    ambiguity_reason
        The reason string returned by
        ``ambiguity_detector.is_ambiguous()``.
    schema_description
        The DDL string describing the database schema (used so the
        model can offer concrete column/table options).
    model
        Groq model identifier.

    Returns
    -------
    str
        A single natural-sounding clarifying question.
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))

    user_content = (
        f"## User's question\n{question}\n\n"
        f"## Ambiguity detected\n{ambiguity_reason}\n\n"
        f"## Database schema\n```sql\n{schema_description}\n```"
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.4,   # slight creativity for natural phrasing
        max_tokens=150,    # one short question is all we need
    )

    clarification = response.choices[0].message.content.strip()

    # Strip wrapping quotes if the model added them.
    if (clarification.startswith('"') and clarification.endswith('"')) or \
       (clarification.startswith("'") and clarification.endswith("'")):
        clarification = clarification[1:-1].strip()

    # Fallback: if the model returned nothing useful, build a question
    # from the ambiguity reason so the caller always gets a response.
    if not clarification:
        parts = ambiguity_reason.split(" | ")
        clarification = "Could you clarify: " + " Also, ".join(
            p.rstrip(".") for p in parts
        ) + "?"

    return clarification


# ── Quick self-test ─────────────────────────────────────────────────────

if __name__ == "__main__":
    from backend.ambiguity_detector import is_ambiguous

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

CREATE TABLE Invoice (
  InvoiceId INTEGER PRIMARY KEY NOT NULL,
  CustomerId INTEGER NOT NULL,
  InvoiceDate DATETIME NOT NULL,
  Total NUMERIC(10,2) NOT NULL
);

CREATE TABLE InvoiceLine (
  InvoiceLineId INTEGER PRIMARY KEY NOT NULL,
  InvoiceId INTEGER NOT NULL REFERENCES Invoice.InvoiceId,
  TrackId INTEGER NOT NULL REFERENCES Track.TrackId,
  UnitPrice NUMERIC(10,2) NOT NULL,
  Quantity INTEGER NOT NULL
);
"""

    test_questions = [
        "Show me the top artists",
        "What is the best album from last quarter?",
    ]

    for q in test_questions:
        result = is_ambiguous(q, sample_ddl)
        if result.is_ambiguous:
            print(f"Q: {q}")
            print(f"   Reason: {result.reason}")
            follow_up = generate_clarifying_question(q, result.reason, sample_ddl)
            print(f"   Follow-up: {follow_up}")
            print()
        else:
            print(f"Q: {q}  →  (not ambiguous, skipping)\n")
