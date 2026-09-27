# Clarify — Context-Aware Text-to-SQL

> Turn natural-language questions into SQL, detect ambiguity, ask for clarification when needed, and safely execute read-only queries.

**Live Demo:** https://clarify-text-to-sql.onrender.com  
**GitHub:** https://github.com/CodeWithNair/clarify-text-to-sql

## Overview

**Clarify** is a full-stack Text-to-SQL application that lets users query a SQLite database using natural language.

Instead of blindly guessing when a query is ambiguous, Clarify can identify missing context and ask the user for clarification before generating SQL.

Example:

> **User:** Who are the top customers?

With **Clarification ON**, Clarify asks what “top” means and how many customers should be returned.

With **Clarification OFF**, Clarify makes an explicit assumption and proceeds.

The project uses the **Chinook SQLite database** as its sample data source.

## Key Features

- Natural-language database queries
- Ambiguity detection
- Interactive clarification
- Clarification ON/OFF modes
- LLM-powered SQL generation
- SQLite / Chinook database support
- Read-only SQL execution
- Destructive-query protection
- Generated SQL visibility
- Tabular query results
- FastAPI backend
- Browser-based frontend
- Render deployment

## How Clarification Works

### Clarification ON

For an ambiguous query:

```text
Who are the top customers?
```

Clarify asks:

```text
Do you want the top customers ranked by total amount spent,
number of invoices, or another metric?
How many top customers would you like to see?
```

The user can answer:

```text
Top 5 by total amount spent
```

The additional context is then used to generate the final SQL query.

### Clarification OFF

The system proceeds using a best-effort assumption:

```text
Assumption:
"top" refers to highest total revenue
(sum of InvoiceLine.UnitPrice × Quantity).
```

This provides a direct comparison between assumption-based and clarification-aware Text-to-SQL.

## Safety

Clarify is designed for **read-only database interaction**.

Destructive SQL operations such as:

```sql
INSERT
UPDATE
DELETE
DROP
```

are rejected rather than executed.

For example:

```text
Drop the customer table.
```

is redirected toward a safe information-retrieval query instead of executing the destructive operation.

## Example Queries

### Clear queries

```text
How many customers are from Brazil?
```

```text
Show the 5 most expensive tracks.
```

```text
How many albums are there?
```

### Ambiguous query

```text
Who are the top customers?
```

With clarification enabled, the system asks for the ranking metric and requested number of customers.

### Genre query

The bundled Chinook database contains the genre:

```text
Hip Hop/Rap
```

Example:

```text
Show me albums in the Hip Hop/Rap genre.
```

The system resolves the Album → Track → Genre relationship and returns matching albums.

## Architecture

```text
Natural Language
       ↓
Ambiguity Detection
       ↓
 ┌─────┴─────┐
 ↓           ↓
Clear      Ambiguous
 ↓           ↓
SQL       Clarification
 ↓           ↓
Execution ← Answer
       ↓
    Results
```

Detailed flow:

```text
Browser Frontend
       ↓
    FastAPI
       ↓
Ambiguity Detector
       ↓
Clarifier (when needed)
       ↓
SQL Generator + LLM
       ↓
Read-only Executor
       ↓
Chinook SQLite Database
       ↓
Results
```

## Project Structure

```text
clarify-text-to-sql/
│
├── backend/
│   ├── main.py
│   ├── schema_loader.py
│   ├── ambiguity_detector.py
│   ├── sql_generator.py
│   ├── clarifier.py
│   └── executor.py
│
├── frontend/
│   └── index.html
│
├── sample_db/
│   └── chinook.db
│
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
│
├── test_ambiguity_signals.py
├── test_dual_mode.py
└── test_e2e.py
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python |
| API | FastAPI |
| LLM | Groq API |
| Database | SQLite |
| Sample Database | Chinook |
| Frontend | HTML, CSS, JavaScript |
| SQL Layer | SQLAlchemy |
| Deployment | Render |
| Version Control | Git / GitHub |

## How It Works

### 1. Schema loading

Clarify loads the database schema so the SQL generation layer can reason about available tables, columns, and relationships.

### 2. Ambiguity detection

The application checks the user's question for ambiguity signals such as vague ranking terms, missing context, or unclear entity references.

### 3. Clarification

If clarification is enabled and ambiguity is detected, the application asks a targeted question instead of immediately guessing.

### 4. SQL generation

Once enough context is available, the LLM generates a SQL query based on the database schema and user intent.

### 5. Safety validation

The generated query is checked so that only read-oriented SQL is executed.

### 6. Execution

The validated SQL query is executed against the Chinook SQLite database.

### 7. Results

Results are returned to the frontend as a table, together with the generated SQL and, when applicable, the assumption made by the system.

## Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/CodeWithNair/clarify-text-to-sql.git
cd clarify-text-to-sql
```

### 2. Create a virtual environment

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file based on `.env.example`:

```env
GROQ_API_KEY=your_api_key_here
```

Do **not** commit `.env` to GitHub.

### 5. Start the application

```bash
uvicorn backend.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

FastAPI documentation:

```text
http://127.0.0.1:8000/docs
```

## API Endpoints

### `GET /health`

Checks whether the backend is running.

### `GET /schema`

Returns the database schema information used by the application.

### `POST /query`

Processes a natural-language database question.

Example:

```json
{
  "question": "Who are the top customers?",
  "clarification_enabled": true
}
```

### `POST /query/resolve`

Processes a clarification answer and continues the original query.

## Deployment

The application is deployed as a Render Web Service.

**Production:** https://clarify-text-to-sql.onrender.com

The service runs FastAPI with Uvicorn and uses environment variables for secrets such as the Groq API key.

## Known Limitations

- Natural-language values may not always exactly match categorical values stored in a database.
- Long chains of unrelated clarification follow-ups can become confusing; starting a fresh query resets the interaction flow.
- The current system is designed around the bundled Chinook SQLite database.
- LLM-generated SQL can occasionally misunderstand user intent and therefore requires validation.
- Render's free service tier may sleep after periods of inactivity.

## Future Improvements

- Better database-value matching
- More robust conversational state management
- Schema-aware entity resolution
- Query explanations
- Support for additional database engines
- Improved SQL validation
- Query history
- More advanced ambiguity detection
- Text-to-SQL evaluation benchmarks

## Project Goal

The goal of Clarify is not simply to convert English into SQL.

It explores a more practical question:

> **What should a Text-to-SQL system do when the user's intent is not specific enough to safely determine a single query?**

By adding an ambiguity-detection and clarification layer, Clarify makes natural-language database interaction more transparent and controllable.

## License

No open-source license is currently specified.
