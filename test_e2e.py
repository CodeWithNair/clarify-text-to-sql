"""End-to-end test of all three query modes against the live server."""
from urllib.request import urlopen, Request
import json, sys

API = "http://127.0.0.1:8000"

def post(path, body):
    req = Request(f"{API}{path}", data=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
    resp = urlopen(req)
    return json.loads(resp.read())

def get(path):
    return json.loads(urlopen(f"{API}{path}").read())

ok = 0; fail = 0

def check(label, cond):
    global ok, fail
    if cond: ok += 1; print(f"  PASS  {label}")
    else: fail += 1; print(f"  FAIL  {label}")

# 1. Health
print("\n=== Health ===")
h = get("/health")
check("health endpoint", h.get("status") == "ok")

# 2. Frontend served at /
print("\n=== Frontend ===")
try:
    html = urlopen(f"{API}/").read().decode()
    check("/ serves HTML", "Clarify" in html and "<html" in html)
except Exception as e:
    check(f"/ serves HTML ({e})", False)

# 3. Clear query (clarification ON)
print("\n=== Clear query: 'How many customers are from Brazil?' ===")
d = post("/query", {"question": "How many customers are from Brazil?", "clarification_enabled": True})
check("action is sql", d["action"] == "sql")
check("SQL is present", bool(d.get("sql")))
check("results is a list", isinstance(d.get("results"), list))
check("results non-empty", len(d.get("results", [])) > 0)
print(f"    → results: {d.get('results')}")

# 4. Ambiguous query (clarification ON)
print("\n=== Ambiguous query (clarification ON): 'Who are the top customers?' ===")
d = post("/query", {"question": "Who are the top customers?", "clarification_enabled": True})
check("action is clarify", d["action"] == "clarify")
check("clarifying_question present", bool(d.get("clarifying_question")))
check("original_question echoed", bool(d.get("original_question")))
print(f"    → question: {d.get('clarifying_question', '')[:100]}")

# 5. Resolve
print("\n=== Resolve: original + 'By total amount spent' ===")
d2 = post("/query/resolve", {
    "original_question": d.get("original_question", "Who are the top customers?"),
    "clarification_answer": "By total amount spent, top 5"
})
check("action is sql", d2["action"] == "sql")
check("SQL present", bool(d2.get("sql")))
check("results present", isinstance(d2.get("results"), list) and len(d2.get("results", [])) > 0)
print(f"    → first row: {d2.get('results', [{}])[0]}")

# 6. Ambiguous query (clarification OFF — best guess)
print("\n=== Ambiguous query (clarification OFF): 'Who are the top customers?' ===")
d3 = post("/query", {"question": "Who are the top customers?", "clarification_enabled": False})
check("action is sql", d3["action"] == "sql")
check("SQL present", bool(d3.get("sql")))
check("results present", isinstance(d3.get("results"), list) and len(d3.get("results", [])) > 0)
check("assumption_made present", bool(d3.get("assumption_made")))
print(f"    → assumption: {d3.get('assumption_made')}")
print(f"    → first row: {d3.get('results', [{}])[0]}")

# 7. /docs still accessible
print("\n=== /docs ===")
try:
    docs = urlopen(f"{API}/docs").read().decode()
    check("/docs serves Swagger UI", "swagger" in docs.lower() or "openapi" in docs.lower())
except Exception as e:
    check(f"/docs accessible ({e})", False)

print(f"\n{'='*50}")
print(f"RESULTS:  {ok} passed,  {fail} failed,  {ok+fail} total")
print(f"{'='*50}")
sys.exit(1 if fail else 0)
