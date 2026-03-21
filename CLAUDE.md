# Cloudista — Claude Configuration

## Project overview

Cloudista is a personal technical blog at cloudista.org. It is a static-ish site served by nginx, with a FastAPI backend that handles blog content (PostgreSQL) and subscriber management (MySQL/MariaDB).

## Repo layout

```
cloudista/
├── api/                  # FastAPI app (deployed as Docker container)
│   ├── main.py           # Subscriber routes + app bootstrap
│   ├── blog_routes.py    # Blog API routes (/api/blog/*)
│   ├── email_template.py # SES email builder
│   ├── Pipfile           # Python deps (use pipenv)
│   └── Dockerfile
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
│   └── schema.sql        # Subscriber DB (MySQL) schema
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

### Two databases

| DB         | Engine     | Purpose               | Host port | Used by            |
|------------|------------|-----------------------|-----------|--------------------|
| blog DB    | PostgreSQL | Posts, tags, authors  | 5433      | `blog_routes.py`   |
| subscriber | MySQL/MariaDB | Email subscriptions | 3306     | `main.py`          |

The blog DB is the primary one. The subscriber DB (MySQL) is occasionally unavailable and non-critical.

### API routes

- `/api/blog/*` — blog content, served from `blog_routes.py` (PostgreSQL)
- `/api/subscribe` `/api/confirm/{token}` — subscriber flow in `main.py` (MySQL)
- `/api/health` — always returns 200; DB status in response body

### New API endpoints

- Blog/content → add to `blog_routes.py`
- Platform/auth/infra → add to `main.py`
- Use `psycopg2` for the blog DB, `pymysql` for the subscriber DB

## Environment variables (production `.env` on server)

```
# Blog DB (PostgreSQL)
BLOG_DB_HOST=localhost
BLOG_DB_PORT=5433
BLOG_DB_USER=cloudista
BLOG_DB_PASSWORD=...

# Subscriber DB (MySQL)
DB_HOST=127.0.0.1
DB_USER=cloudista_api
DB_PASSWORD=...
DB_NAME=cloudista

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

- **`deploy.yml`** — triggered on push to `main` or manually. Auto-detects `--api` vs `--site` from changed paths.
- **`populate-images.yml`** — manual workflow to fetch/update post images against the production DB via SSH tunnel.

GitHub secrets required: `SSH_PRIVATE_KEY`, `SSH_HOST`, `SSH_USER`, `UNSPLASH_ACCESS_KEY`, `PEXELS_ACCESS_KEY`, `BLOG_DB_PASSWORD`.

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
