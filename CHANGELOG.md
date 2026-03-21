# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
