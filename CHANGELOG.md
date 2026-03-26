# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [2026-03-26] — referrer tracking in post view metrics

### Added
- `infra/schema.sql` — `referrer VARCHAR(100)` column added to `post_views` PK `(post_id, viewed_on, country, is_bot, referrer)`; partial index on non-empty referrers
- `api/blog_routes.py` — `_referrer()`: extracts domain from `Referer` header, strips `www.`, filters internal referrers (cloudista.org), truncates at 100 chars; `""` = direct/unknown
- `api/blog_routes.py` — `_record_view()` updated to include referrer in upsert
- `api/blog_routes.py` — `get_post_stats()` adds `top_referrers` query (top-20 by human views)
- `api/schemas.py` — `PostReferrerBreakdown` model; `top_referrers` field on `PostStatsDetail`
- `api/tests/test_blog_routes.py` — 6 new `TestReferrerHelper` tests; updated `TestGetPostStats` assertions to include referrer data

---

## [2026-03-26] — post view metrics with bot detection and geolocation

### Added
- `infra/schema.sql` — `post_views` table: daily time-series keyed on `(post_id, viewed_on, country, is_bot)` composite PK with upsert on conflict; 4 indexes including partial index for human-only queries
- `api/blog_routes.py` — `_is_bot()` (User-Agent regex for 15+ known bots), `_country()` (Cloudflare `CF-IPCountry` header, defaults `XX`), `_record_view()` (non-fatal upsert — analytics failure never affects post delivery)
- `api/blog_routes.py` — `GET /api/posts/{slug}/stats`: daily breakdown (90 days), top-20 countries, 7d/30d/all aggregates split by bot/human (admin key required)
- `api/blog_routes.py` — `GET /api/stats`: top posts by views with `period` filter (`7d`/`30d`/`all`), `include_bots` flag, `limit` param (admin key required)
- `api/blog_routes.py` — Prometheus counter `cloudista_post_views_total` with `slug`/`country`/`is_bot` labels
- `api/schemas.py` — `PostViewDay`, `PostCountryBreakdown`, `PostStatsSummary`, `PostStatsDetail` response models
- `api/tests/test_blog_routes.py` — 23 new tests: `_is_bot`, `_country`, stats endpoints, admin auth enforcement, error paths
- `api/tests/conftest.py` — added `ADMIN_KEY=test-admin-key` env var for stats endpoint tests

---

## [2026-03-26] — add Prometheus metrics endpoint at /metrics

### Added
- `api/Pipfile` — added `prometheus-fastapi-instrumentator==7.0.2`
- `api/main.py` — `Instrumentator` instruments all HTTP routes (request count, duration, in-progress); exposes `/metrics` in Prometheus text format; two custom `Gauge` metrics: `cloudista_subscribers_total` (confirmed subscribers) and `cloudista_posts_published_total` (published posts), refreshed on each `/api/health` poll
- `infra/nginx-cloudista.conf` — added `location = /metrics` proxy block routing to FastAPI
- `api/tests/test_routes.py` — added `TestMetrics` with 3 smoke tests

---

## [2026-03-26] — distinguish DB errors from not-found in preferences endpoint

### Changed
- `api/main.py` — `preferences_page()` now catches `asyncpg.PostgresError` specifically and raises HTTP 503; previously any DB exception silently set `row = None` and returned a "Link not found" page, masking real infrastructure failures

---

## [2026-03-26] — add Turnstile CAPTCHA coverage tests

### Changed
- `api/tests/test_routes.py` — added `TestTurnstile` class with 3 tests: invalid token returns 400, Cloudflare unavailability allows the request (fail-open), and no token skips CAPTCHA check entirely; renamed `test_source_too_long_returns_422` to `test_invalid_source_returns_422`

---

## [2026-03-26] — constrain subscribe source field to known enum values

### Changed
- `api/schemas.py` — replaced free-form `source: str` with `SubscribeSource(str, Enum)` containing four known values (`coming_soon`, `blog`, `landing_page`, `footer`); unknown strings now produce a 422 at validation time
- `api/tests/test_schemas.py` — updated tests to use enum values; replaced `max_length` tests with `test_invalid_source_rejected` and `test_all_valid_sources_accepted`

---

## [2026-03-26] — add TTL to SNS certificate cache

### Changed
- `api/main.py` — `_SNS_CERT_CACHE` now stores `(cert_pem, fetch_time)` tuples; cached certs older than 24 hours are re-fetched so AWS key rotations take effect without a process restart

---

## [2026-03-26] — mask email addresses in log output

### Changed
- `api/main.py` — added `_mask_email()` helper; applied to all three log sites that previously logged full email addresses (`log.info` in `_send_verification`, `log.error` in `_try_send_verification`, `log.error` for token uniqueness violation). Logs now show e.g. `jo***@example.com`
- `api/tests/test_routes.py` — added `TestMaskEmail` class with 4 tests

---

## [2026-03-26] — HTML-escape text content and URL attributes in email templates

### Changed
- `api/email_template.py` — added `import html`; post titles and excerpts are now escaped with `html.escape()` before insertion into HTML; URLs used as `href` attributes are escaped with `html.escape(quote=True)` to handle `&` in query strings correctly
- `api/tests/test_email_template.py` — updated `test_special_characters_in_url_survive` to assert escaped form appears in HTML; added 4 new tests verifying digest/immediate emails escape titles and excerpts

---

## [2026-03-26] — expired prefs link returns error page instead of silent token rotation

### Changed
- `api/main.py` — `preferences_page()` no longer auto-rotates an expired token; returns an error page with message "Your preferences link has expired. Check your most recent email for a new one." instead of silently creating a new token and redirecting
- `api/tests/test_routes.py` — added `test_get_expired_token_returns_error_page` to cover the expired token path

---

## [2026-03-26] — SNS signature verified once at webhook entry point

### Changed
- `api/main.py` — `ses_webhook()` now verifies SNS signature at the top before branching on message type; removes the redundant second verification that was inside the `Notification` branch
- `api/tests/test_routes.py` — updated `test_unknown_type_returns_ignored` to patch `_verify_sns_signature` (now all paths require a valid signature)

---

## [2026-03-26] — simplify token generation, fix health endpoint, reproducible Docker builds

### Changed
- `api/main.py` — `_make_token()` replaced with `secrets.token_urlsafe(32)`; removed `hashlib` import; all call sites updated (email arg dropped)
- `api/main.py` — health endpoint: pool-not-initialised and connection errors both return `db_error = "Unavailable"` instead of distinct internal messages
- `api/Dockerfile` — `--skip-lock` replaced with `--deploy` for reproducible builds (enforces `Pipfile.lock`)

---

## [2026-03-26] — replace 503 with 403 for unconfigured admin key

### Changed
- `api/blog_routes.py` — extracted `_require_admin_key()` FastAPI dependency; missing or wrong `X-Admin-Key` now returns 403 (was: 503 when unconfigured, 403 when wrong)
- `api/tests/test_revisions.py` — updated `test_admin_key_not_configured_returns_503` → `_returns_403`

---

## [2026-03-26] — upgrade to Python 3.12

### Changed
- `api/Dockerfile` — base image updated from `python:3.11-slim` to `python:3.12-slim`
- `api/Pipfile` — `python_version` and `python_full_version` updated to `3.12`
- `.github/workflows/test.yml`, `lint.yml`, `populate-images.yml`, `localize-images.yml` — all updated to `python-version: "3.12"`
- `README.md` — roadmap checklist updated to reflect completion

---

## [2026-03-26] — distinguish transient vs permanent DB errors in blog routes

### Changed
- `api/blog_routes.py` — added `_TRANSIENT_PG_ERRORS` tuple and `_db_error()` helper; all `asyncpg.PostgresError` handlers now return 503 for connection failures and 500 for logic/schema errors
- `api/tests/conftest.py` — added `ConnectionDoesNotExistError`, `ConnectionFailureError`, `CannotConnectNowError` to asyncpg stub
- `api/tests/test_blog_routes.py` — added `test_transient_db_error_returns_503` for list_posts

---

## [2026-03-25] — type hints and tests for blog tooling scripts

### Changed
- `blog/notify_subscribers.py` — added `from __future__ import annotations`, `from typing import Any`; annotated `_ses_client`, `_send`, `run_immediate`, `run_digest`, and `main` with return types
- `scripts/localize_images.py` — added `from typing import Any`; annotated `fix_extensions` `conn` parameter

### Added
- `blog/tests/test_notify_subscribers.py` — 9 tests covering `_send` (dry-run, success, exception) and `run_immediate`/`run_digest` (no-op cases, email dispatch, dry-run guard)
- `scripts/tests/test_localize_images.py` — 19 tests covering `is_external`, `detect_ext`, `ext_for_url`, and `download` (dry-run, success, failure)

---

## [2026-03-25] — request ID propagated into log records

### Changed
- `api/main.py` — added `_request_id_var` context variable and `_RequestIdFilter`; log format updated to `%(request_id)s`; middleware sets the context var at request start and resets it on completion so every log line includes the request ID

---

## [2026-03-25] — cache bust main.js and style.css on all pages

### Changed
- `site/index.html`, `blog-site/index.html`, `blog-site/post.html` — `style.css` and `main.js` references now use `?v=__DEPLOY_HASH__` placeholders
- `api/blog_routes.py` — SSR template updated with same placeholders
- `deploy.sh` — `DEPLOY_HASH` computed once at top-level (not inside the site block) so both site and API deploys substitute correctly; `site/index.html` and SSR template substituted alongside blog HTML

---

## [2026-03-25] — deploy rollback on health check failure

### Changed
- `deploy.sh` — captures previous container image ID before building; if health check fails, automatically restarts the previous image before exiting 1; if no prior image exists, prints instructions and exits 1

---

## [2026-03-25] — extract shared email HTML wrapper

### Changed
- `api/email_template.py` — `build_verification_email` now uses `_email_html_wrapper` (shared with digest/immediate emails) instead of its own copy of the full HTML shell; added `_email_verification_footer_html` for the signup-attribution footer variant; eliminates ~100 lines of duplicated outer HTML

---

## [2026-03-25] — replace hardcoded site URL with settings.site_url

### Changed
- `api/blog_routes.py` — `_SITE_ROOT` now reads from `settings.site_url` instead of the literal `https://cloudista.org`; all downstream sitemap/RSS/JSON-LD URLs inherit the setting
- `api/email_template.py` — imports `settings`; all post URLs in digest and immediate emails use `_SITE_URL = settings.site_url`; footer link also updated
- `api/main.py` — CORS `allow_origins` derived from `settings.site_url` instead of hardcoded strings

---

## [2026-03-25] — DRY tag/category query helper

### Changed
- `api/blog_routes.py` — extracted `_fetch_post_tags_and_categories(conn, post_id)` helper; identical query blocks in `get_post()` and `render_post_page()` replaced with a single call

---

## [2026-03-25] — health check aborts deploy on failure

### Fixed
- `deploy.sh` — health check now exits 1 (abort) instead of printing a warning and continuing; a broken container can no longer produce a green deploy

---

## [2026-03-25] — blog route test coverage

### Added
- `api/tests/test_blog_routes.py` — 30 tests covering all blog API endpoints: `GET /api/posts` (pagination, tag/category filter, validation, DB errors), `GET /api/posts/{slug}` (found, 404, DB error), `GET /api/search` (results, empty, query validation), `GET /api/tags`, `GET /api/categories`, `GET /api/posts/{slug}/related`

---

## [2026-03-25] — fix ruff E402 lint in localize_images.py

### Fixed
- `scripts/localize_images.py` — moved module docstring before `from __future__ import annotations`; ruff was flagging E402 (module-level import not at top of file) because the docstring sat between the `__future__` import and the stdlib imports

---

## [2026-03-25] — deploy-time cache busting for blog.js

### Changed
- `blog-site/index.html`, `blog-site/post.html` — `blog.js` script tag now uses `?v=__DEPLOY_HASH__` placeholder
- `deploy.sh` — substitutes `__DEPLOY_HASH__` with `git rev-parse --short HEAD` via `sed` before SCP on every deploy; ensures browsers load the latest `blog.js` after each release rather than serving a 7-day cached version

---

## [2026-03-25] — fix pagination race condition

### Fixed
- `blog-site/blog.js` — navigating from a paginated category (e.g. `/category/kubernetes/page/3`) to a different category (e.g. `/category/chatops`) would show stale pagination from the previous request; the slow in-flight request for the old category landed after the new one and overwrote the correct state
- Root cause: `activeCategory` was read from outer scope at response time, not at request time; a late response could call `updatePagination` and `pushUrlState` with wrong data
- Fix: capture `activeCategory` (and `searchQuery`) as local snapshots when each fetch is initiated; add `AbortController` so superseded requests are cancelled immediately; `AbortError` is caught and discarded silently

---

## [2026-03-25] — deploy always updates nginx

### Fixed
- `deploy.sh` — nginx config deployment moved out of the API-only guard; now runs in all deploy modes (`--site`, `--api`, full) so `infra/nginx-cloudista.conf` changes always take effect
- `deploy.sh` — nginx `-t` config test runs before `reload`; deploy aborts if config is invalid, preventing a broken reload from taking down the site
- `.github/workflows/deploy.yml` — auto-detect now recognises `infra/` changes as site-side; previously an `infra/`-only commit would not trigger nginx deployment

---

## [2026-03-25] — back link restores category context

### Fixed
- `blog-site/blog.js` — "Back to Blog" on a post page now returns to `/category/<slug>` (or `/category/<slug>/page/N`) when the user arrived from a category-filtered listing; previously it always returned to root

---

## [2026-03-25] — pretty URL pagination + WebP nginx fix

### Changed
- `blog-site/blog.js` — pagination and category filter now use pretty paths: `/page/3`, `/category/aws`, `/category/aws/page/3`; query params (`?page=`, `?category=`) still read as fallback for back-compat
- `infra/nginx-cloudista.conf` — added location blocks for `/page/N`, `/category/slug`, `/category/slug/page/N` (all serve `index.html`); updated `/blog/N` redirect target from `/?page=N` to `/page/N`
- `infra/nginx-cloudista.conf` — WebP content negotiation: replaced `if`+`rewrite` with `try_files` so nginx checks for `.webp` file existence before serving, preventing 404s when no `.webp` variant exists

---

## [2026-03-25] — image localization + import fix

### Added
- `scripts/localize_images.py` — downloads external CDN `image_url`s for all published posts directly to `/www/cloudista.org/images/posts/<slug>.jpg` on the server, then updates DB to the local path; idempotent (skips slugs already on disk)
- `.github/workflows/localize-images.yml` — manual GHA workflow; optionally runs `populate_images.py` first (fills NULL `image_url`s), then SSHes to server and runs `localize_images.py` in-place

### Fixed
- `blog/import_posts.py` — UPDATE path was unconditionally overwriting `image_url` with NULL when a `.txt` file lacked an `Image:` frontmatter field, wiping images set by `populate_images.py` or the `post-image` skill on every re-import; now preserves the existing DB value when frontmatter has no `Image:`

---

## [2026-03-25] — subscriber notifications, analytics, internal linking

### Added
- `api/main.py` — `GET/POST /api/preferences/{token}` subscriber frequency preference page; 1-year `prefs_token` with transparent auto-rotation on expiry
- `api/email_template.py` — `build_digest_email()` and `build_immediate_email()` for weekly digest and per-post immediate notifications; shared footer helpers
- `api/schemas.py` — `PreferencesIn` model (`frequency: Literal["weekly", "immediate"]`)
- `blog/notify_subscribers.py` — standalone script; `--mode immediate` sends unnotified posts to immediate-frequency subscribers; `--mode digest` sends weekly batch; `--dry-run` flag
- `.github/workflows/notify-immediate.yml` — cron every 30 min; SCPs script to server and runs immediate notify
- `.github/workflows/notify-digest.yml` — cron Sundays 14:00 UTC (9 AM ET); runs weekly digest
- `.github/workflows/list-hygiene.yml` — cron Mondays 06:00 UTC; purges `status='pending'` subscribers older than 30 days; dry-run default on manual dispatch
- `blog/check_internal_links.py` — cluster-aware script to report missing internal links across related posts; `--cluster`, `--verbose` flags
- Plausible privacy-friendly analytics on all pages (`site/index.html`, `blog-site/index.html`, `blog-site/post.html`, SSR head in `api/blog_routes.py`)
- RSS feed at `/feed.xml`; Subscribe modal on blog listing page
- Internal links added across ~41 posts in 8 topic clusters: Terraform (7 posts), Kubernetes (9 posts), Security/secrets (8 posts), Go/gRPC (5 posts), CI/CD (5 posts), Lambda (3 posts), SaltStack (4 posts), NFCU 2-part series
- `README.md` — productization roadmap, 3-month revenue roadmap; MySQL migration section removed

### Changed
- Subscribe route generates `prefs_token` + `prefs_token_expires_at` on INSERT and rotates on resend/resubscribe
- Verification email footer now includes "Manage preferences" link when `prefs_url` is set
- `POST /api/preferences/{token}` accepts `application/x-www-form-urlencoded` (HTML form) via FastAPI `Form()`; `python-multipart` added to `Pipfile`
- `api/blog_routes.py` — removed `html.escape()` wrapper on `image_credit` in SSR template (trusted HTML from DB was being double-encoded)
- Blog migrated to main page (`/`); coming-soon timer removed
- `blog/populate_images.py` — added keyword mapping for calendar/routine posts

### Fixed
- `POST /api/preferences/{token}` validation error returned 500 instead of 422 for invalid frequency values; now catches `ValidationError` and raises `HTTPException(422)`
- Auto-deploy detection: `git diff HEAD~1` fails with `fetch-depth: 1`; workaround is manual `gh workflow run deploy.yml --field mode=api`

### Schema migrations (run once on production)
```sql
ALTER TABLE subscribers
  ADD COLUMN IF NOT EXISTS frequency             VARCHAR(20) NOT NULL DEFAULT 'weekly',
  ADD COLUMN IF NOT EXISTS last_digest_at        TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS prefs_token           CHAR(64) UNIQUE,
  ADD COLUMN IF NOT EXISTS prefs_token_expires_at TIMESTAMPTZ;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_posts_unnotified ON posts (published_at DESC)
  WHERE status = 'published' AND notified_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_subscribers_prefs_token ON subscribers (prefs_token)
  WHERE prefs_token IS NOT NULL;
```

---

## [Unreleased] — refactor/python-backend

### Added
- `api/config.py` — Pydantic `BaseSettings` for all configuration; `ValidationError` at startup if required env vars missing; `ses_topic_arn` for SNS topic allowlist
- `api/dependencies.py` — asyncpg connection pool (min 2, max 10) with FastAPI `Depends()` for automatic connection lifecycle; shared `limiter` and `_real_ip` used across routers
- `api/schemas.py` — all Pydantic request/response models consolidated; `response_model` on all routes; `source` field restricted to `^[a-z0-9_]+$`
- `TurnstileResult` enum (`VALID` / `INVALID` / `UNAVAILABLE`) — Cloudflare outage now fails open instead of blocking all subscriptions
- `infra/schema.sql` — `token_expires_at TIMESTAMPTZ` column added; redundant `idx_subscribers_token` index removed (covered by UNIQUE constraint)
- `scripts/migrate_subscribers_to_pg.py` — one-time migration script to move subscriber data from MySQL → PostgreSQL; idempotent (`ON CONFLICT DO NOTHING`)
- `GET /api/unsubscribe/{token}` — one-click unsubscribe endpoint; token included in every verification email footer
- `POST /api/ses-webhook` — SNS bounce/complaint handler with RSA-SHA1 signature verification and SSRF-safe cert URL validation
- Rate limiting via `slowapi`: `5/minute` on `/api/subscribe`, `30/minute` on `/api/search`
- Token expiry: 72-hour TTL on all verification tokens; expired tokens redirect to `?confirmed=expired`
- Token rotation: resend always issues a new token, invalidating any previously sent link
- Request-ID middleware: echoes/generates `X-Request-ID`; strips control characters to prevent CRLF injection
- Unit tests (`api/tests/`) with pass/fail/edge coverage for all routes; `pytest-asyncio` + `httpx` test client; asyncpg stubbed for CI without a live DB
- `.github/workflows/test.yml` — test CI; must pass before merge to main
- Branch protection: `lint`, `test`, and `required_signatures` (verified commits) all enforced on main

### Changed
- **Single database** — MySQL/MariaDB subscriber DB removed; `subscribers` table now lives in the same PostgreSQL instance as blog content
- **All routes async** — `psycopg2` replaced with `asyncpg`; all SQL uses `$N` positional parameters; routes are `async def`
- `api/main.py` — FastAPI `lifespan` context manager initialises/closes the PG pool; all routes use `Depends(get_pg_conn)`; `asyncio.to_thread()` for sync SES/Turnstile calls
- `api/blog_routes.py` — full async/asyncpg conversion; `image_credit` escaped with `html.escape()` in server-rendered HTML (was stored XSS)
- `api/email_template.py` — unsubscribe link added to HTML footer and plain-text; "72 hours" expiry note added
- `deploy.sh` — `StrictHostKeyChecking=no` removed; `_trust_host()` populates `~/.ssh/known_hosts` via `ssh-keyscan`; `.env` scaffold warns if `BLOG_DB_PASSWORD` is empty; `SES_TOPIC_ARN` added to scaffold
- `.github/workflows/populate-images.yml` — shell injection fix: slug input passed via `env:` block, not inline `${{ inputs.slug }}`; `StrictHostKeyChecking=no` removed
- `infra/nginx-cloudista.conf` — Cloudflare real-IP module configured (`set_real_ip_from` for all CF CIDRs); `CF-Connecting-IP` cleared on all proxy locations; full security header set added (CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy)
- `api/main.py` confirm route — only `pending` rows can be confirmed; `confirmed` and `unsubscribed` both redirect to `?confirmed=already`

### Fixed
- `api/main.py` subscriber re-send path — `token` column was missing from SELECT; accessing `row["token"]` raised `KeyError` in production for any subscriber who submitted twice
- `blog/populate_images.py` — inverted provider detection (`"urls" in photo` check was backwards, misidentifying Pexels photos as Unsplash)
- Stored XSS in `blog_routes.py` — `image_credit` field rendered unescaped in server-rendered post HTML
- Rate limit bypass — `CF-Connecting-IP` was used as rate-limit key; clients bypassing Cloudflare could inject arbitrary IPs; switched to nginx-set `X-Real-IP`
- SSRF in SNS webhook — `startswith("https://sns.amazonaws.com/")` was bypassable; replaced with `re.fullmatch` on parsed hostname

### Removed
- `psycopg2-binary` dependency from `api/Pipfile` (replaced by `asyncpg`)
- `pymysql` dependency from `api/Pipfile`
- MySQL-specific env vars (`DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_PORT`)
- MySQL `GRANT ... IDENTIFIED BY` user-creation logic from `deploy.sh`

---

## [2026-03-21] — linting + repo organisation

### Added
- Linting for all languages: `ruff` (Python), `yamllint` (YAML), `shellcheck` (shell), `eslint` (JavaScript)
- `ruff.toml`, `eslint.config.mjs`, `.yamllint.yml` config files at repo root
- `package.json` with `eslint` + `@eslint/js` + `globals` as devDependencies
- `.github/workflows/lint.yml` — reviewdog-powered lint CI; inline PR annotations on pull requests, check annotations on push to main
- `.github/workflows/populate-images.yml` — manual workflow to fetch post images via SSH tunnel to production DB
- `CLAUDE.md` — contributor config: architecture, make targets, post format, env vars, CI/CD overview
- Branch protection on `main`: PRs required, `Lint / lint` must pass, direct pushes blocked (enforced for admins)
- GitHub Actions secrets: `UNSPLASH_ACCESS_KEY`, `PEXELS_ACCESS_KEY`, `BLOG_DB_PASSWORD`, `GOOGLE_API_KEY`
- Repo made public (required for branch protection on free GitHub plan)

### Changed
- 227 Python lint violations fixed (import ordering, `Optional[T]` → `T | None`, line length)
- YAML workflow files: added `---` document start markers, quoted `on:` key
- `api/health` endpoint always returns HTTP 200; DB status reported in response body instead of 503
- `deploy.sh` and `Makefile` updated to use new source paths after repo reorganisation

### Added (repo structure)
- `site/` — landing site pages (`index.html`, `style.css`, `main.js`, `privacy.html`, `terms.html`, `robots.txt`)
- `site/assets/` — favicons, `og-image.png`, `site.webmanifest`
- `infra/` — `nginx-cloudista.conf`, `schema.sql`
- `scripts/` — operational tools (`verify_pending.py`, `make_favicon.py`, `make_og_image.py`)

### Removed
- `.DS_Store`, `review.md`, `sitemap.xml` (gitignored scratch files)
- `make_favicon.py`, `make_og_image.py` from repo root (moved to `scripts/`)

---

## [2026-03-20] — initial commit

### Added
- FastAPI backend (`api/`) with blog routes (PostgreSQL) and subscriber routes (MySQL)
- Blog content pipeline: `blog/import_posts.py`, `blog/populate_images.py`, `blog/tag_posts.py`
- 188 blog posts imported, all with unique hero images (Unsplash / Pexels)
- Static landing site (`site/`), blog frontend (`blog-site/`)
- `Makefile` with targets for deploy, import, image population, local dev, SSH, logs
- `deploy.sh` — SSH-based deploy to EC2 (vabch.org); auto-detects `--api` / `--site` / full from changed files
- nginx config, PostgreSQL schema, Docker setup
- GitHub remote at `github.com/morissette/cloudista`
- `.github/workflows/deploy.yml` — CI/CD on push to `main`

