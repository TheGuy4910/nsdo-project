# NSDO Phase 6 — Decisions and Limitations

## Decisions made in Phase 6 (as approved)

### Decision A — First-user bootstrap
The first `POST /api/auth/register` request is accepted from anyone and
creates an admin user. All subsequent registrations require an existing
admin's Bearer token. There is no default password and no seed-data
credential. Bootstrap is triggered by `count_users(db) == 0`.

### Decision B — JWT_SECRET_KEY
Read from the `JWT_SECRET_KEY` environment variable. If absent, a
development fallback constant is used (`INSECURE-DEV-ONLY-DO-NOT-USE-IN-PRODUCTION`)
with a `WARNING`-level log message at startup. The app does not refuse to
start — the sandbox/local-without-Docker path must remain functional.
`docker-compose.yml` sets a dev default that includes a timestamp suffix
to avoid accidentally sharing keys across instances.

To generate a production key:
```
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Decision C — Read endpoints are public
All `GET /api/*` endpoints remain unauthenticated except `GET /api/auth/me`.
Write operations (POST/PUT/DELETE) require an admin Bearer token via
`Depends(require_admin)`. This reflects the published-research nature of
the data — viewing, analysing, and exporting requires no login.

### Decision D — Provenance headers in exported CSV
Both `GET /api/datasets/{id}/export.csv` and `GET /api/observations/export.csv`
include provenance header rows prefixed with `#` at the top of the file.
These follow the same convention as `hesa_uk_real_figures.csv` and
`SYNTHETIC_DO_NOT_TREAT_AS_REAL.csv` in the fixture directory.
The headers include: source name, reliability tier, metric definition,
reference period, destination country, stated limitations, original URL.

---

## New files in Phase 6

### Backend
- `backend/app/services/auth.py` — pure password hashing (bcrypt via passlib)
  and JWT creation/verification (python-jose). No FastAPI dependency.
- `backend/app/api/auth.py` — /token, /register, /me endpoints and the
  shared `require_admin` FastAPI dependency.
- `backend/tests/test_auth.py` — auth service unit tests.

### Frontend
- `frontend/login.html` — login form; token stored in sessionStorage.
- `frontend/docs.html` — methodology and data integrity documentation page.

---

## Modified files in Phase 6

### Backend
- `backend/app/schemas.py` — `UserCreate`, `UserRead`, `Token`, `TokenData`
- `backend/app/crud.py` — `get_user_by_username`, `count_users`, `create_user`;
  `User` moved to top-level import
- `backend/app/main.py` — auth router registered; version 0.6.0-phase6
- `backend/app/api/sources.py` — `require_admin` on POST/PUT/DELETE
- `backend/app/api/datasets.py` — `require_admin` on POST/PUT/DELETE;
  `GET /api/datasets/{id}/export.csv` added
- `backend/app/api/import_csv.py` — `require_admin` on commit; preview stays open
- `backend/app/api/import_xlsx.py` — `require_admin` on commit
- `backend/app/api/admin.py` — `require_admin` on POST /api/admin/seed
- `backend/app/api/observations.py` — `GET /api/observations/export.csv` added
- `docker-compose.yml` — `JWT_SECRET_KEY` env var added

### Frontend
- `frontend/nsdo.js` — `auth` object added; `apiFetch`/`apiFormData` send
  Bearer token automatically; 'docs' page added to nav; `docIcon()` added;
  `auth` exported on `window.NSDO`
- `frontend/datasets.html` — characteristics panel in detail modal (lazy-loads
  observations and their sub-dimensions); export button in modal footer;
  auth-state sign-in prompt

---

## Packages used (all already in requirements.txt)

- `passlib[bcrypt]==1.7.4` — bcrypt password hashing
- `python-jose[cryptography]==3.3.0` — JWT creation and verification
- `python-multipart==0.0.9` — OAuth2PasswordRequestForm body parsing

No new packages were added to requirements.txt.

---

## Docker verification result (post-Phase-6)

**Status: PASSED — gate resolved.**

```
docker compose exec -T api python3 -m unittest discover -s tests -p "test_*.py"
Ran 236 tests
OK (skipped=0)
```

236/236 passed, 0 errors, 0 skipped in the Docker container.

### Bugs found and fixed during verification

**Bug 1 — `seed_runtime.py` line ~176: invalid kwarg on `Observation()`**
- `imported_by="seed_runtime" if hasattr(Observation, "imported_by") else None`
  was passed to `Observation()` which has no `imported_by` column.
- The ternary changed the value but not whether the kwarg was passed.
- `imported_by=None` was always sent → always raised `TypeError`.
- **Fix:** deleted that line. `Dataset()` above it correctly keeps its own `imported_by`.

**Bug 2 — `requirements.txt`: bcrypt 4.1.0+ breaks passlib 1.7.4**
- `passlib 1.7.4` reads `bcrypt.__about__.__version__` at init time.
- That attribute was removed in `bcrypt 4.1.0`.
- Without a pin, pip installed `bcrypt ≥ 4.1.0`, breaking all password hashing.
- **Fix:** added `bcrypt==4.0.1` as an explicit pin in `requirements.txt`.

---

## Known limitations entering Phase 7

1. **No token refresh** — 8-hour JWTs, no refresh endpoint.
2. **No user management UI** — users created via `/api/auth/register` only.
3. **Password complexity** — only minimum 8 characters enforced.
4. **sessionStorage** — token cleared on tab close (intentional).
5. **Export limit** — up to 2,000 observations per export call.
6. **DOCKER_VERIFY.sh** — written before Phase 6 auth/export; should be
   extended with Phase 6 smoke tests (auth bootstrap, export endpoints,
   protected-route 401/403 checks).
