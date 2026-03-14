---
phase: 03-auth-api-signup
verified: 2026-03-14T17:42:52Z
status: passed
score: 4/4 must-haves verified
re_verification: false
---

# Phase 3: Auth + API Signup Verification Report

**Phase Goal:** Developers can sign up, receive an API key, and authenticate all requests — the service is a real product, not a stub
**Verified:** 2026-03-14T17:42:52Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                                     | Status     | Evidence                                                                                             |
|----|-----------------------------------------------------------------------------------------------------------|------------|------------------------------------------------------------------------------------------------------|
| 1  | Developer hits POST /v1/auth/signup, receives plaintext API key shown once, can immediately use it        | VERIFIED   | test_signup_success + test_signup_key_works_immediately pass; signup returns 201 with ml_ key, key works on /_test/tenant |
| 2  | Plaintext key never stored — only SHA-256 hash in DB; breach does not expose usable keys                  | VERIFIED   | test_signup_key_not_stored_plaintext passes; create_api_key only receives key_hash, schema has no plaintext column |
| 3  | Developer can rotate API key and all previously stored memories are accessible with the new key            | VERIFIED   | test_rotate_preserves_memories passes; deactivate_keys_for_tenant only touches api_keys table, tenant_id unchanged |
| 4  | Any request missing a valid Bearer token receives structured 401 JSON, not 500 or HTML                    | VERIFIED   | test_401_structured_json + test_401_includes_www_authenticate_header + test_error_responses_are_json_not_html pass |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact                          | Expected                                  | Status    | Details                                                                        |
|-----------------------------------|-------------------------------------------|-----------|--------------------------------------------------------------------------------|
| `app/routers/auth.py`             | signup + rotation endpoints               | VERIFIED  | 86 lines; POST /signup (201) and POST /keys/rotate (200) both substantive      |
| `app/db/system.py`                | deactivate_keys_for_tenant helper         | VERIFIED  | Function at line 154; atomic UPDATE sets is_active=0, returns rowcount         |
| `app/deps.py`                     | Auth dependency resolves Bearer to tenant | VERIFIED  | get_tenant hashes key with SHA-256, queries DB, raises 401 on any failure      |
| `app/main.py`                     | Global exception handlers                 | VERIFIED  | http_exception_handler, validation_exception_handler, unhandled_exception_handler all present |
| `app/models/schemas.py`           | SignupResponse + KeyRotateResponse        | VERIFIED  | Both Pydantic models present with api_key field; neither model stores raw key in DB schema |
| `tests/test_auth_signup.py`       | Signup endpoint tests                     | VERIFIED  | 7 tests — success, key works immediately, hash-only storage, dupe 409, validation 422s, no-auth-required |
| `tests/test_auth_rotate.py`       | Rotation integration tests                | VERIFIED  | 7 tests — new key returned, old key 401, new key works, memories preserved, auth required, invalid key, double rotate |
| `tests/test_error_handlers.py`    | Error handler tests                       | VERIFIED  | 7 tests — 401 structured JSON, WWW-Authenticate header, 422 structured, 404 structured, Content-Type, last_used_at |

### Key Link Verification

| From                    | To                     | Via                                          | Status  | Details                                                              |
|-------------------------|------------------------|----------------------------------------------|---------|----------------------------------------------------------------------|
| `app/routers/auth.py`   | `app/db/system.py`     | deactivate_keys_for_tenant + create_api_key  | WIRED   | Both imported at line 14; rotate_key calls both in sequence          |
| `app/routers/auth.py`   | `app/deps.py`          | Depends(get_tenant) on rotate endpoint       | WIRED   | get_tenant imported line 15; rotate_key signature uses Depends(get_tenant) at line 64 |
| `app/deps.py`           | `app/db/system.py`     | get_tenant_by_key_hash + update_key_last_used| WIRED   | Both imported line 17; called within get_tenant on every auth        |
| `app/main.py`           | `app/routers/auth.py`  | app.include_router(auth_router)              | WIRED   | auth_router imported and included at lines 24 + 133                  |
| Signup endpoint         | tenant_manager         | create_tenant_db after api_key creation      | WIRED   | Line 51 calls create_tenant_db; test_rotate_preserves_memories verifies memory endpoints work immediately after signup |

### Requirements Coverage

| Requirement | Status    | Notes                                                                                      |
|-------------|-----------|--------------------------------------------------------------------------------------------|
| AUTH-01     | SATISFIED | POST /v1/auth/signup returns 201 with API key; test_signup_success verifies format and fields |
| AUTH-02     | SATISFIED | Only key_hash stored in api_keys; test_signup_key_not_stored_plaintext directly queries DB to confirm |
| AUTH-03     | SATISFIED | get_tenant dependency wired to all protected routes via Depends; test_create_memory_no_auth + test_401 verify enforcement |
| AUTH-04     | SATISFIED | deps.py: Authorization header → split Bearer → SHA-256 hash → get_tenant_by_key_hash → tenant dict |
| AUTH-05     | SATISFIED | deactivate_keys_for_tenant touches only api_keys table; tenant_id unchanged; test_rotate_preserves_memories is a live end-to-end proof |
| AUTH-06     | SATISFIED | StarletteHTTPException handler in main.py returns {"error":"UNAUTHORIZED","message":"..."} with WWW-Authenticate: Bearer header |

### Anti-Patterns Found

None. No TODO/FIXME/placeholder comments found in any phase-modified file. No stub return values. No empty handlers.

### Human Verification Required

None. All success criteria are deterministically verifiable via tests.

The following tests constitute end-to-end proof for each success criterion:

1. **Developer receives key and can use it immediately** — `test_signup_success` + `test_signup_key_works_immediately`
2. **Plaintext never stored** — `test_signup_key_not_stored_plaintext` queries the live SQLite DB and asserts stored value equals SHA-256 of the key, not the key itself
3. **Rotation preserves memories** — `test_rotate_preserves_memories` creates a memory, rotates the key, retrieves the memory with the new key
4. **401 is structured JSON** — `test_401_structured_json` + `test_error_responses_are_json_not_html` assert Content-Type and body shape

### Test Suite Result

```
183 passed in 12.04s
```

All 183 tests pass, including:
- 7 tests in test_auth_signup.py
- 7 tests in test_auth_rotate.py
- 7 tests in test_error_handlers.py

### Security Model Verification

The `create_api_key` function signature is `(conn, key_id, tenant_id, key_hash, key_prefix, name)` — the parameter is named `key_hash`, not `api_key`. The caller in both signup and rotate passes `key_hash` (the SHA-256 digest), never `plaintext`. The `api_keys` table schema has a `key_hash TEXT NOT NULL UNIQUE` column and no column that could hold the full 67-character key. A complete dump of `api_keys` gives an attacker nothing usable.

---
_Verified: 2026-03-14T17:42:52Z_
_Verifier: Claude (gsd-verifier)_
