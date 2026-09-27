# Clarify — Context-Aware Text-to-SQL with Ambiguity Resolution

Clarify is a natural-language interface for querying relational databases without requiring users to write SQL.

Instead of simply translating a question into SQL, Clarify can detect when a user's request is ambiguous, ask a targeted clarification question, and then generate and safely execute the final SQL query.

The project demonstrates a complete pipeline from **natural language → ambiguity detection → clarification → SQL generation → safe execution → database results**.

---

## What It Does

Clarify allows users to ask database questions using natural language.

For example:

> "How many customers are from Brazil?"

The system generates the appropriate SQL query, executes it against the database, and displays the actual results.

For ambiguous questions, Clarify can pause before generating SQL and ask the user to provide the missing information.

The system supports two modes:

### Clarification ON

The system detects ambiguity and asks the user for clarification before proceeding.

### Clarification OFF

The system skips the clarification step and allows the SQL generation layer to make a reasonable assumption before executing the query.

This makes it possible to compare both approaches using the same question.

---

## Why the Clarification Engine Matters

Traditional Text-to-SQL systems can generate syntactically valid SQL even when the original question is underspecified.

For example:

> **"Who are the top customers?"**

"Top" does not define a ranking metric.

It could mean:
- highest total spending
- most purchases
- highest average order value
- another metric

Instead of silently choosing one interpretation, Clarify can detect the ambiguity and ask the user what they mean.

With **Clarification ON**, the system asks for the missing information.

With **Clarification OFF**, the system can proceed using an explicit assumption.

This creates a transparent distinction between:

**Ask before assuming**  
and  
**Make a smart assumption and continue**

The clarification engine focuses on ambiguity signals such as vague superlatives, missing time ranges, and potentially ambiguous entity matches.

---

## Architecture

```text
                    User
                      │
                      ▼
             Natural Language Query
                      │
                      ▼
              ┌───────────────┐
              │    FastAPI    │
              │   API Layer   │
              └───────┬───────┘
                      │
                      ▼
             ┌──────────────────┐
             │ Schema Loader    │
             │ Database Schema  │
             └────────┬─────────┘
                      │
                      ▼
             ┌──────────────────┐
             │ Ambiguity        │
             │ Detector         │
             └────────┬─────────┘
                      │
              ┌───────┴────────┐
              │                │
       Ambiguous            Clear /
       + ON                  OFF
              │                │
              ▼                │
        Clarification          │
              │                │
              ▼                │
       User's Answer           │
              │                │
              └───────┬────────┘
                      ▼
             ┌──────────────────┐
             │   SQL Generator  │
             │   Groq LLM       │
             └────────┬─────────┘
                      │
                      ▼
             ┌──────────────────┐
             │  Safe Executor   │
             │   Read-Only SQL  │
             └────────┬─────────┘
                      │
                      ▼
                SQLite Database
                      │
                      ▼
               Query Results
                      │
                      ▼
                  Frontend