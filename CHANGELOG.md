# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased] — refactor/python-backend

### Added
- `api/config.py` — Pydantic `BaseSettings` for all configuration; `ValidationError` at startup if required env vars missing
- `api/dependencies.py` — `ThreadedConnectionPool` (min 2, max 10) with FastAPI `Depends()` for automatic connection lifecycle; replaces per-request connect/close in every route
- `api/schemas.py` — all Pydantic request/response models consolidated; `response_model` on all routes
- `TurnstileResult` enum (`VALID` / `INVALID` / `UNAVAILABLE`) — Cloudflare outage now fails open instead of blocking all subscriptions
- `infra/schema.sql` rewritten for PostgreSQL — `GENERATED ALWAYS AS IDENTITY`, `TIMESTAMPTZ`, `CHECK` constraint instead of `ENUM`, no charset declarations
- `scripts/migrate_subscribers_to_pg.py` — one-time migration script to move subscriber data from MySQL → PostgreSQL; idempotent (`ON CONFLICT DO NOTHING`)

### Changed
- **Single database** — MySQL/MariaDB subscriber DB removed; `subscribers` table now lives in the same PostgreSQL instance as blog content
- `api/main.py` — FastAPI `lifespan` context manager initialises/closes the PG pool; subscriber routes use `Depends(get_pg_conn)` from `dependencies.py`
- `api/blog_routes.py` — all routes use `Depends(get_pg_conn)`; schemas imported from `schemas.py`
- `deploy.sh` — MySQL user-creation block replaced with a simple `.env` scaffold (PG vars only)
- `blog/import_posts.py` — per-post commits instead of single end-of-loop commit; `updated` counter tracked separately from `inserted`; hardcoded DSN removed
- `blog/tag_posts.py` — `run()` split into `seed_taxonomy()` and `apply_tags()`; per-post transactions replace bulk delete-and-reinsert
- `blog/populate_images.py` — fetch retry waterfall extracted into `_fetch_with_fallback()`; hardcoded DSN fallback removed; provider detection bug fixed

### Fixed
- `api/main.py` subscriber re-send path — `token` column was missing from `SELECT id, status FROM subscribers`; accessing `row["token"]` raised `KeyError` in production for any subscriber who submitted twice
- `blog/populate_images.py` — inverted provider detection (`"urls" in photo` check was backwards, misidentifying Pexels photos as Unsplash)

### Removed
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
