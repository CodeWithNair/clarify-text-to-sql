# text-to-sql-clarify

Natural-language to SQL with intelligent clarification support, powered by FastAPI and LLMs.

## Project Structure

```
text-to-sql-clarify/
├── backend/
│   ├── __init__.py
│   ├── schema_loader.py   # Introspects SQLite schema → structured DDL
│   ├── sql_generator.py   # LLM-powered NL→SQL with clarification loop
│   └── main.py            # FastAPI application & endpoints
├── sample_db/
│   └── chinook.db         # Chinook sample database (SQLite)
├── .env.example           # Environment variable template
├── requirements.txt       # Python dependencies
└── README.md
```

## Quick Start

```bash
# 1. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your API key
copy .env.example .env
# Edit .env and set OPENAI_API_KEY

# 4. Run the server
uvicorn backend.main:app --reload
```

The API will be available at **http://127.0.0.1:8000**.  
Interactive docs at **http://127.0.0.1:8000/docs**.

## API Endpoints

| Method | Path           | Description                                |
|--------|----------------|--------------------------------------------|
| GET    | `/health`      | Health check                               |
| GET    | `/schema`      | Return database schema (DDL + summary)     |
| POST   | `/ask`         | Ask a natural-language question             |
| POST   | `/ask/clarify` | Continue a clarification conversation       |
| GET    | `/query`       | Execute raw SQL (dev/debug)                |

### Example: Ask a question

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How many tracks are there in each genre?"}'
```

### Example response (SQL generated)

```json
{
  "action": "sql",
  "sql": "SELECT g.Name AS Genre, COUNT(t.TrackId) AS TrackCount FROM Genre g JOIN Track t ON g.GenreId = t.GenreId GROUP BY g.Name ORDER BY TrackCount DESC;",
  "explanation": "Counts the number of tracks per genre by joining Genre and Track tables.",
  "results": [
    {"Genre": "Rock", "TrackCount": 1297},
    {"Genre": "Latin", "TrackCount": 579}
  ]
}
```

### Example response (Clarification needed)

```json
{
  "action": "clarify",
  "questions": [
    "Do you mean total revenue or revenue per customer?",
    "Should the results be filtered by a specific time period?"
  ],
  "conversation_history": [...]
}
```

## Database

Uses the [Chinook](https://github.com/lerocha/chinook-database) sample database — a digital media store with 11 tables covering artists, albums, tracks, invoices, customers, and employees.

## Environment Variables

| Variable          | Default         | Description                        |
|-------------------|-----------------|------------------------------------|
| `OPENAI_API_KEY`  | *(required)*    | Your I APIgrooQ key                |
| `LLM_MODEL`       | `gpt-4o-mini`   | Model identifier                   |
| `OPENAI_BASE_URL` | *(unset)*       | Override for local model endpoints |
| `DATABASE_PATH`   | `sample_db/chinook.db` | Path to the SQLite database  |
