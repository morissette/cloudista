# Cloudista — Claude Configuration

## Project overview

Cloudista is a personal technical blog at cloudista.org. It is a static-ish site served by nginx, with a FastAPI backend that handles blog content and subscriber management, both on a single PostgreSQL instance.

## Repo layout

```
cloudista/
├── api/                  # FastAPI app (deployed as Docker container)
│   ├── main.py           # Subscriber + webhook routes + app bootstrap
│   ├── blog_routes.py    # Blog API routes (/api/blog/*)
│   ├── config.py         # Pydantic BaseSettings (all env vars)
│   ├── dependencies.py   # asyncpg pool + get_pg_conn dependency
│   ├── schemas.py        # All Pydantic request/response models
│   ├── email_template.py # SES email builder
│   ├── Pipfile           # Python deps (use pipenv)
│   ├── Dockerfile
│   └── tests/            # Unit + integration tests (pytest)
├── blog/                 # Blog content + import tools
│   ├── *.txt             # Post source files (YYYY-MM-slug.txt)
│   ├── import_posts.py   # Import .txt → PostgreSQL
│   ├── populate_images.py # Fetch images from Unsplash/Pexels
│   └── tag_posts.py      # Keyword→category tagging
├── blog-site/            # Blog frontend (static HTML/JS)
│   ├── index.html        # Listing page
│   ├── post.html         # Single post page
│   └── blog.js           # SPA logic
├── site/                 # Landing site (deployed to web root)
│   ├── assets/           # Favicons, og-image.png, site.webmanifest
│   ├── index.html
│   ├── privacy.html
│   ├── terms.html
│   ├── style.css
│   ├── main.js
│   └── robots.txt
├── infra/                # Infrastructure config
│   ├── nginx-cloudista.conf
│   └── schema.sql        # PostgreSQL schema (subscribers + indexes)
├── images/               # Post images (served at /images/)
├── scripts/              # Operational one-off tools
├── .github/workflows/    # CI/CD
├── deploy.sh             # Deployment script (called by CI and make)
└── Makefile              # All operations — prefer `make` over running scripts directly
```

## Always use `make`

Use `make <target>` for all operations. Never run `deploy.sh`, `ssh`, or docker commands directly.

```
make deploy           # full deploy (site + API + nginx)
make site             # static files only
make api              # API Docker rebuild + restart only
make import           # import blog .txt posts into local PostgreSQL
make populate-images  # fetch images for posts missing one (requires UNSPLASH_ACCESS_KEY)
make new-post SLUG=x  # scaffold a new post
make logs             # tail live container logs
make health           # hit /api/health on production
make ssh              # interactive SSH to vabch.org
make db-shell         # psql into remote blog DB
make dev              # local DB + API with hot-reload
```

## Architecture

### Single PostgreSQL database

All data — blog posts, tags, authors, and subscribers — lives in one PostgreSQL instance.

| Schema area  | Engine     | Purpose                        | Used by            |
|--------------|------------|--------------------------------|--------------------|
| blog tables  | PostgreSQL | Posts, tags, authors, images   | `blog_routes.py`   |
| subscribers  | PostgreSQL | Email subscriptions + tokens   | `main.py`          |

### API routes

- `/api/blog/*` — blog content, served from `blog_routes.py`
- `/api/subscribe` — register email; sends verification via SES (rate limited: 5/min/IP)
- `/api/confirm/{token}` — confirm subscription (token expires in 72 hours)
- `/api/unsubscribe/{token}` — self-service unsubscribe (link in every email)
- `/api/ses-webhook` — SNS bounce/complaint handler; marks bad addresses unsubscribed
- `/api/health` — always returns 200; DB status in response body

### New API endpoints

- Blog/content → add to `blog_routes.py`
- Platform/auth/subscriber infra → add to `main.py`
- All routes must be `async def`; use `asyncpg` via `get_pg_conn` dependency
- SQL parameters use `$1, $2, ...` (asyncpg positional placeholders, not `%s`)

## Testing

**Every new feature or bug fix must include unit tests.** Tests live in `api/tests/`.

```bash
# Run all tests
cd api && pytest tests/ -v

# Run a specific test file
cd api && pytest tests/test_routes.py -v
```

### Test structure

| File | What it covers |
|------|---------------|
| `tests/test_email_template.py` | Email rendering, URLs, content |
| `tests/test_schemas.py` | Pydantic validation pass/fail/edge |
| `tests/test_routes.py` | All route endpoints with mocked DB |
| `tests/conftest.py` | Stubs for asyncpg/boto3 (no real packages needed locally) |

### Test requirements

- **Pass tests**: happy path for every route/function
- **Fail tests**: invalid input, missing fields, DB errors
- **Edge tests**: expiry boundaries, duplicate emails, rate limit threshold
- DB must be mocked (no live DB in tests); use `app.dependency_overrides[get_pg_conn]`
- The `test` GitHub Actions job must pass before any PR can merge to `main`

## Environment variables (production `.env` on server)

```
# PostgreSQL (blog + subscribers)
BLOG_DB_HOST=localhost
BLOG_DB_PORT=5433
BLOG_DB_USER=cloudista
BLOG_DB_PASSWORD=...
BLOG_DB_NAME=cloudista

# AWS SES
AWS_REGION=us-east-1
FROM_EMAIL=noreply@cloudista.org
CONFIRM_BASE_URL=https://cloudista.org/api/confirm
SITE_URL=https://cloudista.org

# Cloudflare Turnstile
TURNSTILE_SECRET=...
```

## Blog post format

Posts live in `blog/YYYY-MM-slug.txt`:

```
Title: My Post Title
Author: Marie H.
Date: 2026-03-20
Image: https://images.unsplash.com/photo-...?w=900&q=80&fm=webp&auto=format&fit=crop
Tags: kubernetes, devops
============================================================

Post content in Markdown...
```

**Every new post must include an `Image:` frontmatter field.**

Use `make new-post SLUG=my-slug` to scaffold. After writing, run `make import` to push to DB.

## Adding images to posts

```bash
# Fetch images for all posts missing one
UNSPLASH_ACCESS_KEY=... PEXELS_ACCESS_KEY=... python3 blog/populate_images.py

# Target a specific post
UNSPLASH_ACCESS_KEY=... python3 blog/populate_images.py --slug my-post-slug

# Or trigger via GitHub Actions → "Populate Post Images" workflow
```

Image fallback chain: Unsplash → keyword alt query → "devops {keywords}" → "platform engineering {keywords}" → Pexels.

## CI/CD

GitHub Actions at `.github/workflows/`:

- **`lint.yml`** — ruff, yamllint, shellcheck, eslint via reviewdog; must pass before merge
- **`test.yml`** — pytest on every PR and push to main; must pass before merge
- **`deploy.yml`** — triggered on push to `main` or manually. Auto-detects `--api` vs `--site` from changed paths.
- **`populate-images.yml`** — manual workflow to fetch/update post images against the production DB via SSH tunnel.

GitHub secrets required: `SSH_PRIVATE_KEY`, `SSH_HOST`, `SSH_USER`, `UNSPLASH_ACCESS_KEY`, `PEXELS_ACCESS_KEY`, `BLOG_DB_PASSWORD`, `TURNSTILE_SECRET`, `GOOGLE_API_KEY`.

## Local dev

```bash
make dev          # starts cloudista-db (Docker, postgres:16 on :5433) + uvicorn with hot-reload
make db-shell     # psql into remote production DB
```

Local PostgreSQL: `postgresql://cloudista:cloudista_dev@localhost:5433/cloudista`

## Deployment flow

1. Push to `main` → GitHub Actions detects changed files → runs `deploy.sh --api` or `--site` or full
2. `deploy.sh` SSHes into `vabch.org`, builds Docker image, restarts container
3. Health check hits `/api/health` — warns on non-200 but never fails the build
