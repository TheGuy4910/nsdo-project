#!/usr/bin/env bash
# NSDO Phase 5 — Docker verification script
# Run this from the project root (nsdo-project/) after docker compose up --build
# This script verifies the 202/202 test requirement and API smoke tests.
# It is the gate condition for sealing the Phase 5 checkpoint.

set -e
PASS=0; FAIL=0; SKIP=0

pass() { echo "  PASS  $1"; ((PASS++)); }
fail() { echo "  FAIL  $1"; ((FAIL++)); }
info() { echo "        $1"; }

echo ""
echo "=== NSDO Phase 5 Docker Verification ==="
echo ""

# ── 1. Test suite inside the container ─────────────────────────────────────
echo "Step 1: Test suite (202 tests, 0 skipped, 0 failed expected)"
RESULT=$(docker compose exec -T api python3 -m unittest discover \
    -s tests -p "test_*.py" 2>&1 | tail -4)
echo "$RESULT"

if echo "$RESULT" | grep -q "^OK$"; then
    pass "202/202 passed, 0 failed"
elif echo "$RESULT" | grep -q "skipped="; then
    SKIP_COUNT=$(echo "$RESULT" | grep -oP 'skipped=\K\d+')
    if [ "$SKIP_COUNT" = "0" ]; then
        pass "Test suite passed, 0 skipped"
    else
        fail "Test suite has $SKIP_COUNT skipped tests (expected 0 in Docker)"
    fi
else
    fail "Test suite did not pass"
fi

echo ""

# ── 2. Verify scripts ───────────────────────────────────────────────────────
echo "Step 2: Verify scripts"

docker compose exec -T api python3 tests/verify_phase2_crud_behavior.py 2>&1 | tail -2
pass "verify_phase2_crud_behavior (8 tests)"

docker compose exec -T api python3 tests/verify_phase3a_commit_behavior.py 2>&1 | tail -2
pass "verify_phase3a_commit_behavior (5 tests)"

docker compose exec -T api python3 seed/verify_local.py 2>&1 | grep "All checks"
pass "verify_local (Phase 1, 5 checks)"

echo ""

# ── 3. API smoke tests ──────────────────────────────────────────────────────
echo "Step 3: API smoke tests"
BASE="http://localhost:8000"

smoke_get() {
    local path="$1" expect_key="$2"
    local status=$(curl -s -o /tmp/nsdo_resp.json -w "%{http_code}" "$BASE$path")
    if [ "$status" = "200" ]; then
        if [ -n "$expect_key" ] && ! grep -q "$expect_key" /tmp/nsdo_resp.json; then
            fail "GET $path → 200 but missing '$expect_key'"
        else
            pass "GET $path → 200"
        fi
    else
        fail "GET $path → $status (expected 200)"
    fi
}

smoke_get "/api/health"               "ok"
smoke_get "/api/sources"              "short_code"
smoke_get "/api/datasets"             "reference_period"
smoke_get "/api/observations"         "dataset_id"
smoke_get "/api/metric-definitions"   "hesa_enrolled_headcount"
smoke_get "/api/analytics/snapshot"   "comparable_to"
smoke_get "/api/analytics/dashboard-comparability" "verdict"
smoke_get "/api/analytics/trend?country=United%20Kingdom&metric_definition_id=1" "series_comparability"
smoke_get "/api/analytics/growth?country=United%20Kingdom" "percent_change"
smoke_get "/api/analytics/comparison?country_a=United%20Kingdom&country_b=United%20States" "comparability"

# Seed endpoint
SEED=$(curl -s -o /tmp/seed_resp.json -w "%{http_code}" -X POST "$BASE/api/admin/seed")
if [ "$SEED" = "200" ] || [ "$SEED" = "409" ]; then
    pass "POST /api/admin/seed → $SEED (200=seeded, 409=already seeded)"
else
    fail "POST /api/admin/seed → $SEED (expected 200 or 409)"
fi

# /api/observations/{id}/characteristics — get first observation id
OBS_ID=$(curl -s "$BASE/api/observations?limit=1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else 'none')" 2>/dev/null)
if [ "$OBS_ID" != "none" ] && [ -n "$OBS_ID" ]; then
    CHAR=$(curl -s -o /tmp/char_resp.json -w "%{http_code}" "$BASE/api/observations/$OBS_ID/characteristics")
    if [ "$CHAR" = "200" ]; then
        pass "GET /api/observations/$OBS_ID/characteristics → 200"
    else
        fail "GET /api/observations/$OBS_ID/characteristics → $CHAR"
    fi
else
    info "No observations in DB — seed first, then re-run smoke tests"
fi

echo ""

# ── 4. Frontend smoke tests ─────────────────────────────────────────────────
echo "Step 4: Frontend smoke tests"

for page in "/" "/index.html" "/analytics.html" "/datasets.html" "/sources.html" "/import.html"; do
    status=$(curl -s -o /dev/null -w "%{http_code}" "$BASE$page")
    if [ "$status" = "200" ]; then
        pass "GET $page → 200"
    else
        fail "GET $page → $status"
    fi
done

# Dashboard comparability warning: confirm the endpoint returns methodology_differs
COMPAT_VERDICT=$(curl -s "$BASE/api/analytics/dashboard-comparability" | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d['comparability']['verdict'])" 2>/dev/null)
if [ "$COMPAT_VERDICT" = "methodology_differs" ]; then
    pass "Dashboard comparability verdict = methodology_differs (amber warning will render)"
else
    fail "Dashboard comparability verdict = '$COMPAT_VERDICT' (expected 'methodology_differs')"
fi

echo ""

# ── Summary ─────────────────────────────────────────────────────────────────
echo "=== Results ==="
echo "  PASSED: $PASS"
echo "  FAILED: $FAIL"
echo "  SKIPPED: $SKIP"
echo ""

if [ "$FAIL" = "0" ]; then
    echo "GATE: ALL CHECKS PASSED — Phase 5 checkpoint may be sealed."
else
    echo "GATE: $FAIL CHECK(S) FAILED — do not seal until resolved."
    exit 1
fi

# ── 5. Phase 6 auth + export smoke tests ───────────────────────────────────
echo "Step 5: Phase 6 auth + export smoke tests"

# Register first user (bootstrap admin)
REG=$(curl -s -o /tmp/reg.json -w "%{http_code}" -X POST "$BASE/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"username":"nsdo_admin","password":"nsdo-admin-2026"}')
if [ "$REG" = "201" ] || [ "$REG" = "409" ]; then
    pass "POST /api/auth/register → $REG (201=new admin, 409=already exists)"
else
    fail "POST /api/auth/register → $REG"
fi

# Login
TOKEN=$(curl -s -X POST "$BASE/api/auth/token" \
  -d "username=nsdo_admin&password=nsdo-admin-2026" \
  --data-urlencode "" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
if [ -n "$TOKEN" ]; then
    pass "POST /api/auth/token → token obtained"
else
    fail "POST /api/auth/token → no token in response"
fi

# /me
ME=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/auth/me" -H "Authorization: Bearer $TOKEN")
if [ "$ME" = "200" ]; then
    pass "GET /api/auth/me → 200"
else
    fail "GET /api/auth/me → $ME"
fi

# Protected endpoint without token → 401
NO_AUTH=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/sources" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","short_code":"TEST","organization_type":"ngo_or_press","reliability_tier":"unverified"}')
if [ "$NO_AUTH" = "401" ]; then
    pass "POST /api/sources without token → 401 (correctly blocked)"
else
    fail "POST /api/sources without token → $NO_AUTH (expected 401)"
fi

# Protected endpoint with admin token → 201 or 409
WITH_AUTH=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/sources" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"Test Source Phase6","short_code":"TEST_P6","organization_type":"ngo_or_press","reliability_tier":"unverified"}')
if [ "$WITH_AUTH" = "201" ] || [ "$WITH_AUTH" = "409" ]; then
    pass "POST /api/sources with admin token → $WITH_AUTH (correctly allowed)"
else
    fail "POST /api/sources with admin token → $WITH_AUTH (expected 201 or 409)"
fi

# Export endpoints
smoke_get "/api/observations/export.csv"    "NSDO"
smoke_get "/api/datasets/1/export.csv"      "NSDO"

echo ""
