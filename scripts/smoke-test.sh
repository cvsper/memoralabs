#!/bin/bash
# MemoraLabs Post-Deploy Smoke Test
# Usage: ./scripts/smoke-test.sh [BASE_URL]
# Default: https://memoralabs-api.onrender.com
#
# Runs a full API lifecycle test: health -> signup -> store -> search -> gaps
# Creates a real tenant account (timestamped email, won't collide).

set -euo pipefail

BASE_URL="${1:-https://memoralabs-api.onrender.com}"
PASS=0
FAIL=0

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    PASS=$((PASS + 1))
}

fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    FAIL=$((FAIL + 1))
}

# Helper: make a curl call, return "BODY\nSTATUS_CODE"
# Usage: curl_call METHOD URL [extra curl args...]
curl_call() {
    local method="$1"
    local url="$2"
    shift 2
    curl -s -w "\n%{http_code}" -X "$method" "$url" "$@"
}

# Parse status code (last line of curl -w "\n%{http_code}" output)
get_status() {
    echo "$1" | tail -1
}

# Parse body (everything except last line)
get_body() {
    echo "$1" | head -n -1
}

echo "============================================"
echo "  MemoraLabs Post-Deploy Smoke Test"
echo "  BASE_URL: $BASE_URL"
echo "============================================"
echo ""

# -----------------------------------------------
# Step 1: Health check
# -----------------------------------------------
echo "--- Step 1: Health Check ---"
RESPONSE=$(curl_call GET "${BASE_URL}/health" \
    -H "Accept: application/json")
STATUS=$(get_status "$RESPONSE")
BODY=$(get_body "$RESPONSE")

if [ "$STATUS" = "200" ] && echo "$BODY" | python3 -c "import sys, json; d=json.load(sys.stdin); assert 'healthy' in (d.get('status',''))" 2>/dev/null; then
    pass "GET /health returned 200 with 'healthy' status"
else
    fail "GET /health failed (HTTP $STATUS). Body: $BODY"
fi
echo ""

# -----------------------------------------------
# Step 2: Signup
# -----------------------------------------------
echo "--- Step 2: Signup ---"
EMAIL="smoke-$(date +%s)@test.dev"
PASSWORD="SmokeTest123!"
RESPONSE=$(curl_call POST "${BASE_URL}/v1/auth/signup" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -d "{\"email\": \"${EMAIL}\", \"password\": \"${PASSWORD}\"}")
STATUS=$(get_status "$RESPONSE")
BODY=$(get_body "$RESPONSE")

API_KEY=$(echo "$BODY" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('api_key',''))" 2>/dev/null || echo "")

if [ "$STATUS" = "201" ] && [ -n "$API_KEY" ]; then
    pass "POST /v1/auth/signup returned 201 and api_key extracted"
else
    fail "POST /v1/auth/signup failed (HTTP $STATUS). Body: $BODY"
    echo "Cannot continue without API key. Aborting."
    echo ""
    echo "============================================"
    echo "  SMOKE TEST RESULT: FAILED ($PASS passed, $FAIL failed)"
    echo "============================================"
    exit 1
fi
echo ""

# -----------------------------------------------
# Step 3: Store memory
# -----------------------------------------------
echo "--- Step 3: Store Memory ---"
CONTENT="MemoraLabs smoke test at $(date)"
RESPONSE=$(curl_call POST "${BASE_URL}/v1/memory" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    -d "{\"content\": \"${CONTENT}\", \"metadata\": {\"source\": \"smoke-test\"}}")
STATUS=$(get_status "$RESPONSE")
BODY=$(get_body "$RESPONSE")

MEMORY_ID=$(echo "$BODY" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")

if [ "$STATUS" = "201" ] && [ -n "$MEMORY_ID" ]; then
    pass "POST /v1/memory returned 201 and memory id extracted"
else
    fail "POST /v1/memory failed (HTTP $STATUS). Body: $BODY"
fi
echo ""

# -----------------------------------------------
# Step 4: Search memories
# -----------------------------------------------
echo "--- Step 4: Search Memories ---"
RESPONSE=$(curl_call POST "${BASE_URL}/v1/memory/search" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    -d "{\"query\": \"smoke test\"}")
STATUS=$(get_status "$RESPONSE")
BODY=$(get_body "$RESPONSE")

RESULTS_COUNT=$(echo "$BODY" | python3 -c "import sys, json; d=json.load(sys.stdin); print(len(d.get('results', [])))" 2>/dev/null || echo "0")

if [ "$STATUS" = "200" ] && [ "$RESULTS_COUNT" -gt 0 ]; then
    pass "POST /v1/memory/search returned 200 with $RESULTS_COUNT result(s)"
else
    fail "POST /v1/memory/search failed (HTTP $STATUS) or empty results ($RESULTS_COUNT). Body: $BODY"
fi
echo ""

# -----------------------------------------------
# Step 5: Gap detection
# -----------------------------------------------
echo "--- Step 5: Gap Detection ---"
RESPONSE=$(curl_call POST "${BASE_URL}/v1/intelligence/gaps" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    -d "{}")
STATUS=$(get_status "$RESPONSE")
BODY=$(get_body "$RESPONSE")

if [ "$STATUS" = "200" ]; then
    pass "POST /v1/intelligence/gaps returned 200"
else
    fail "POST /v1/intelligence/gaps failed (HTTP $STATUS). Body: $BODY"
fi
echo ""

# -----------------------------------------------
# Summary
# -----------------------------------------------
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}All smoke tests passed.${NC} ($PASS passed, 0 failed)"
    echo "============================================"
    exit 0
else
    echo -e "  ${RED}Smoke tests FAILED.${NC} ($PASS passed, $FAIL failed)"
    echo "============================================"
    exit 1
fi
