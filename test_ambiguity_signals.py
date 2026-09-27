"""
test_ambiguity_signals.py
─────────────────────────
Confirms that all 3 ambiguity signals in ambiguity_detector.py fire
correctly against the real Chinook database schema.

Signal (a): Vague superlatives without a metric
Signal (b): Unresolved time references without a date range
Signal (c): Entity names colliding with multiple schema locations
"""

import sys
from pathlib import Path

# Ensure project root is on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.schema_loader import load_schema
from backend.ambiguity_detector import is_ambiguous

# ── Load real Chinook schema ────────────────────────────────────────────

DB_PATH = Path(__file__).resolve().parent / "sample_db" / "chinook.db"
schema = load_schema(DB_PATH)
ddl = schema.to_ddl()

passed = 0
failed = 0


def check(label: str, question: str, expect_ambiguous: bool, expect_substr: str = ""):
    """Run one test case and report pass/fail."""
    global passed, failed
    result = is_ambiguous(question, ddl)

    ok = result.is_ambiguous == expect_ambiguous
    if expect_ambiguous and expect_substr:
        ok = ok and (expect_substr.lower() in result.reason.lower())

    status = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1

    print(f"  [{status}] {label}")
    print(f"         Q: {question}")
    print(f"         Expected ambiguous={expect_ambiguous}", end="")
    if expect_substr:
        print(f', reason contains "{expect_substr}"', end="")
    print()
    if not ok:
        print(f"         GOT: ambiguous={result.is_ambiguous}, reason={result.reason!r}")
    print()


# ═══════════════════════════════════════════════════════════════════════
# Signal (a): Vague superlatives
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("SIGNAL (a): Vague superlatives without a metric")
print("=" * 70)

# Should trigger
check("a.1 - 'top' without metric",
      "Show me the top artists",
      expect_ambiguous=True, expect_substr="top")

check("a.2 - 'best' without metric",
      "What is the best album?",
      expect_ambiguous=True, expect_substr="best")

check("a.3 - 'most' without metric",
      "Which genre is the most popular?",
      expect_ambiguous=True, expect_substr="most")

check("a.4 - 'highest' without metric",
      "Which employee has the highest performance?",
      expect_ambiguous=True, expect_substr="highest")

# Should NOT trigger (metric or number+noun present)
check("a.5 - 'top 10' with number+noun (clear)",
      "List the top 10 tracks by sales",
      expect_ambiguous=False)

check("a.6 - 'most' with metric hint (clear)",
      "Which genre has the most tracks?",
      expect_ambiguous=False)

check("a.7 - 'highest' with metric hint (clear)",
      "Which album has the highest total revenue?",
      expect_ambiguous=False)


# ═══════════════════════════════════════════════════════════════════════
# Signal (b): Unresolved time references
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("SIGNAL (b): Unresolved time references")
print("=" * 70)

# Should trigger
check("b.1 - 'recent' without date",
      "Show me the most recent invoices",
      expect_ambiguous=True, expect_substr="recent")

check("b.2 - 'last month' without date",
      "How many customers signed up last month?",
      expect_ambiguous=True, expect_substr="last month")

check("b.3 - 'last quarter' without date",
      "What was the revenue last quarter?",
      expect_ambiguous=True, expect_substr="last quarter")

check("b.4 - 'this year' without date",
      "Show sales this year",
      expect_ambiguous=True, expect_substr="this year")

check("b.5 - 'past few months' without date",
      "Which artists were popular in the past few months?",
      expect_ambiguous=True, expect_substr="past")

# Should NOT trigger (explicit date present)
check("b.6 - explicit ISO date (clear)",
      "Show invoices from 2024-01-01 to 2024-03-31",
      expect_ambiguous=False)

check("b.7 - no time reference at all (clear)",
      "List all customers from Brazil",
      expect_ambiguous=False)


# ═══════════════════════════════════════════════════════════════════════
# Signal (c): Entity collisions (multiple schema locations)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print('SIGNAL (c): Entity names matching multiple schema locations')
print("=" * 70)

# "name" appears in Artist.Name, Genre.Name, Track.Name, MediaType.Name, Playlist.Name
check("c.1 - 'name' matches 5+ columns",
      "Show me all the name values",
      expect_ambiguous=True, expect_substr="name")

# "title" appears in Album.Title AND Employee.Title
check("c.2 - 'title' matches Album.Title + Employee.Title",
      "Search by title",
      expect_ambiguous=True, expect_substr="title")

# Should NOT trigger (unique / ignored words only)
check("c.3 - 'composer' is unique to Track (clear)",
      "Show me the composer for each track",
      expect_ambiguous=False)

check("c.4 - 'email' appears in Customer + Employee",
      "Show me the email addresses",
      expect_ambiguous=True, expect_substr="email")

check("c.5 - specific table name, no collision (clear)",
      "List all genres",
      expect_ambiguous=False)


# ═══════════════════════════════════════════════════════════════════════
# Combined signals
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("COMBINED: Multiple signals in one question")
print("=" * 70)

check("combo.1 - superlative + time",
      "What is the best album from last quarter?",
      expect_ambiguous=True, expect_substr="best")

check("combo.2 - superlative + entity collision",
      "Show me the top name",
      expect_ambiguous=True, expect_substr="top")

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print(f"RESULTS:  {passed} passed,  {failed} failed,  {passed + failed} total")
print("=" * 70)

sys.exit(1 if failed else 0)
