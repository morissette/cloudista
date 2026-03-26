# Cloudista — Repo Improvement Areas (Round 2)

Top 10 actionable improvements following the Round 1 refactor (PRs #70–#79).
Ordered by practical impact for a solo developer.

---

## 1. Generic error messages in blog_routes.py hide critical DB bugs

**File:** `api/blog_routes.py` lines 186–189, 242–245, 263–266, 307–309

Routes like `get_post()`, `related_posts()`, `list_revisions()`, and `restore_revision()` catch all `asyncpg.PostgresError` with identical generic messages ("Failed to fetch post."). Constraint violations, connection timeouts, and schema bugs are indistinguishable to operators.

**Fix:** Distinguish transient errors (connection pool exhausted, timeout → 503) from permanent errors (schema mismatch, bad query → 500). Log the specific `asyncpg` error subclass so problems are diagnosable. Match the pattern in `main.py` line 472 which already handles `UniqueViolationError` specifically.

---

## 2. SQL fragmented across list_posts() — schema changes need multi-site edits

**File:** `api/blog_routes.py` lines 116–165

`list_posts()` manually assembles WHERE/JOIN clauses across multiple string literals. The base query, tag filter, and category filter are all separate fragments. New routes copy-paste this pattern. A schema column rename requires updating every fragment across every route.

**Fix:** Extract a `_build_post_list_query()` helper that owns the select fields, joins, and filter logic as a single source of truth. Routes pass parameters, not fragments.

---

## 3. Misleading 503 status when admin_key is unconfigured

**File:** `api/blog_routes.py` lines 278–281

`restore_revision()` returns 503 ("Service unavailable") when `settings.admin_key` is unset. This is semantically wrong — the service is running fine, it's just not configured. 503 tells monitoring systems the service is down.

**Fix:** Create a `require_admin_key` FastAPI dependency that returns 403 for both missing configuration and wrong key. Move this logic out of the route handler so it's reusable across any admin-gated route.

---

## 4. SNS signature verification runs twice per webhook request

**File:** `api/main.py` lines 648–673

`ses_webhook()` calls `_verify_sns_signature(body)` separately for `SubscriptionConfirmation` and `Notification`. Each call fetches and validates the cert. On a cache miss, this doubles latency for every bounce/complaint notification.

**Fix:** Move signature verification to a single guard at the top of `ses_webhook()` before branching on message type. One cert fetch, one verification, clearer security boundary.

---

## 5. Email template builders don't HTML-escape inputs

**File:** `api/email_template.py` lines 177–276

`build_verification_email()`, `build_digest_email()`, and `build_immediate_email()` interpolate URLs and post data (slug, title, excerpt) directly into HTML without escaping. Currently safe because callers construct these values programmatically, but one future change that allows user-supplied content would create an XSS vector.

**Fix:** Apply `html.escape()` to all text fields and `urllib.parse.quote()` to all URL-interpolated values inside the builders. Defense in depth: the builder resists injection even when callers forget.

---

## 6. Health endpoint leaks internal initialization state

**File:** `api/main.py` line 360

The health endpoint returns `db_error = "Pool not initialised"` as a distinct error from `"Connection failed"`. This tells an attacker (or monitoring system) that the app started but the DB pool never initialized — more detail than needed.

**Fix:** Return a single generic message (`"Unavailable"`) for all DB error states. Operators can read the detailed error from structured logs. The health endpoint should signal degradation (useful for load balancers), not expose internals.

---

## 7. Token generation uses hash where a random token suffices

**File:** `api/main.py` lines 144–146

`_make_token()` constructs a string from `email + uuid4 + timestamp`, then SHA256-hashes it. The timestamp component is unnecessary and adds entropy analysis surface. The approach is functional but adds accidental complexity — the UUID alone provides 128 bits of entropy, which is sufficient.

**Fix:** Replace with `secrets.token_urlsafe(32)` (256 bits, URL-safe, constant-time generation). Simpler, idiomatic, and more readable.

---

## 8. Preferences endpoint silently rotates tokens without user awareness

**File:** `api/main.py` lines 576–598

When a user clicks an expired preferences link, the endpoint generates a new token, updates the DB, and silently redirects to the new URL. The user never knows the link expired. More importantly, this means any request to an old preferences URL triggers a DB write — a side-effectful GET request.

**Fix:** Return 403 with a user-facing message ("Your preferences link has expired — check your most recent email for an updated link.") instead of auto-rotating. Eliminates the side-effectful GET and the silent state change.

---

## 9. No tests for partial transaction failures or connection pool exhaustion

**File:** `api/tests/test_routes.py` — 107 tests, but gaps remain

There are no tests for:
- Two simultaneous subscribe requests for the same email (race condition, should hit `UniqueViolationError`)
- `_try_send_verification` failing after the DB insert succeeds (subscriber is confirmed but gets no email)
- Connection pool exhausted at startup (pool size 10 in `dependencies.py:63`)

These scenarios have no safety net at the code level.

**Fix:** Add tests that mock `UniqueViolationError` on the second concurrent subscribe, and mock SES failure after a successful DB insert, asserting the DB row is still present and the error is logged.

---

## 10. Dockerfile installs with --skip-lock, breaking reproducibility

**File:** `api/Dockerfile` lines 8–9

```dockerfile
RUN pipenv install --system --skip-lock
```

`--skip-lock` ignores `Pipfile.lock` and resolves transitive dependencies fresh from PyPI on every build. The same git commit produces different container images if any upstream package releases a new version between deployments.

**Fix:** Remove `--skip-lock`. Use `pipenv install --system --deploy` which enforces the lockfile and fails the build if `Pipfile.lock` is out of sync. Run `pipenv lock` locally when adding dependencies, then commit the updated lockfile.

---

## Summary

| # | File | Issue | Impact | Effort |
|---|------|-------|--------|--------|
| 1 | `blog_routes.py` | Generic DB errors hide root causes | Medium | Low |
| 2 | `blog_routes.py` | Fragmented SQL query assembly | Medium | Medium |
| 3 | `blog_routes.py` | 503 instead of 403 for unconfigured admin key | Low | Low |
| 4 | `main.py` | Double SNS signature verification per request | Low | Low |
| 5 | `email_template.py` | No HTML escaping on template inputs | Low | Low |
| 6 | `main.py` | Health endpoint leaks initialization state | Low | Very Low |
| 7 | `main.py` | Overly complex token generation | Low | Very Low |
| 8 | `main.py` | Side-effectful GET rotates prefs token silently | Low | Medium |
| 9 | `api/tests/` | Missing concurrency + partial-failure tests | Medium | Medium |
| 10 | `api/Dockerfile` | Non-reproducible builds via --skip-lock | Medium | Low |
