"""Test both clarification_enabled modes against the live server."""
from urllib.request import urlopen, Request
import json

BASE = "http://127.0.0.1:8002"
QUESTION = "Show me the top artists"


def post(endpoint, payload):
    req = Request(
        f"{BASE}{endpoint}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(urlopen(req).read())


print("=" * 60)
print("TEST 1: clarification_enabled=True (default)")
print("=" * 60)
resp = post("/query", {"question": QUESTION})
print(f"  action:              {resp['action']}")
print(f"  clarifying_question: {resp.get('clarifying_question')}")
print(f"  assumption_made:     {resp.get('assumption_made')}")
print(f"  sql:                 {resp.get('sql')}")
print()

print("=" * 60)
print("TEST 2: clarification_enabled=False (best-guess)")
print("=" * 60)
resp = post("/query", {"question": QUESTION, "clarification_enabled": False})
print(f"  action:          {resp['action']}")
print(f"  assumption_made: {resp.get('assumption_made')}")
print(f"  sql:             {(resp.get('sql') or '')[:120]}...")
results = resp.get("results") or []
print(f"  result count:    {len(results)}")
for row in results[:5]:
    print(f"    {row}")
