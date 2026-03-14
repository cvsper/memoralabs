# MemoraLabs Quickstart

Store and recall your first memory in under 5 minutes.

**Prerequisites:** Just `curl` (or Python 3 with `requests`). No SDK needed.

---

## Step 1: Sign Up

One POST request creates your account and returns your API key.

```bash
curl -s -X POST https://memoralabs.onrender.com/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"name": "Your Name", "email": "you@example.com"}' | python3 -m json.tool
```

Expected response:

```json
{
  "tenant_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "email": "you@example.com",
  "plan": "free",
  "api_key": "ml_abc123...",
  "key_prefix": "ml_abc1",
  "message": "Store this API key securely. It will not be shown again."
}
```

> **Save your `api_key` value. It is shown exactly once.**

Set it as an environment variable for the commands below:

```bash
export MEMORA_KEY="ml_abc123..."
```

---

## Step 2: Store a Memory

```bash
curl -s -X POST https://memoralabs.onrender.com/v1/memory \
  -H "Authorization: Bearer $MEMORA_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "The user prefers dark mode and metric units"}' | python3 -m json.tool
```

Expected response:

```json
{
  "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "text": "The user prefers dark mode and metric units",
  "status": "created",
  "created_at": 1700000000,
  "updated_at": 1700000000
}
```

Store a second memory for the search demo:

```bash
curl -s -X POST https://memoralabs.onrender.com/v1/memory \
  -H "Authorization: Bearer $MEMORA_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "Meeting with Alice scheduled for Friday at 2pm", "metadata": {"type": "calendar"}}' | python3 -m json.tool
```

---

## Step 3: Search Memories

Search understands meaning, not just keywords — semantic similarity returns the most relevant result even when the query words differ from the stored text.

```bash
curl -s -X POST https://memoralabs.onrender.com/v1/memory/search \
  -H "Authorization: Bearer $MEMORA_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "what are the user display preferences?"}' | python3 -m json.tool
```

The response includes `memories_used` and `memories_limit` so you can track usage against your plan:

```json
{
  "results": [
    {
      "id": "b2c3d4e5-...",
      "text": "The user prefers dark mode and metric units",
      "score": 0.87
    }
  ],
  "total": 1,
  "memories_used": 2,
  "memories_limit": 1000
}
```

---

## Step 4: List All Memories

```bash
curl -s https://memoralabs.onrender.com/v1/memory \
  -H "Authorization: Bearer $MEMORA_KEY" | python3 -m json.tool
```

Returns a paginated list ordered newest-first. Add `?page=2&page_size=50` for pagination, or `?user_id=alice` to filter by scope.

---

## Python Example

Complete standalone script — copy, paste, run:

```python
import requests

BASE = "https://memoralabs.onrender.com"

# 1. Sign up
r = requests.post(f"{BASE}/v1/auth/signup", json={
    "name": "Alice",
    "email": "alice@example.com"
})
api_key = r.json()["api_key"]
headers = {"Authorization": f"Bearer {api_key}"}

# 2. Store a memory
requests.post(f"{BASE}/v1/memory", headers=headers, json={
    "text": "The user prefers dark mode and metric units"
})

# 3. Store another
requests.post(f"{BASE}/v1/memory", headers=headers, json={
    "text": "Meeting with Alice scheduled for Friday at 2pm",
    "metadata": {"type": "calendar"}
})

# 4. Search
r = requests.post(f"{BASE}/v1/memory/search", headers=headers, json={
    "query": "display preferences"
})
for result in r.json()["results"]:
    print(f"[{result['score']:.2f}] {result['text']}")
```

---

## Error Handling

All errors return a consistent structure:

```json
{
  "error": "UNAUTHORIZED",
  "message": "Missing Authorization header"
}
```

Common codes:

| Code | HTTP | When |
|------|------|------|
| `UNAUTHORIZED` | 401 | Missing or invalid API key |
| `NOT_FOUND` | 404 | Memory ID does not exist |
| `VALIDATION_ERROR` | 422 | Request body failed validation |
| `RATE_LIMITED` | 429 | Too many requests |
| `CONFLICT` | 409 | Email already registered |

---

## What's Next?

- **Explore all endpoints:** [API Docs](https://memoralabs.onrender.com/docs)
- **Rotate your API key:** `POST /v1/auth/keys/rotate`
- **Extract entities from a memory:** `GET /v1/memory/{id}/entities`
- **Filter search by metadata:** Add `"metadata_filter": {"type": "calendar"}` to your search request
- **Scope memories by user/agent/session:** Pass `user_id`, `agent_id`, or `session_id` on store and filter on list/search
