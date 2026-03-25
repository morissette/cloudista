# cloudista.org

Personal technical blog covering DevOps, platform engineering, Kubernetes, cloud infrastructure, and SRE. Live at [cloudista.org](https://cloudista.org).

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Static HTML/CSS/JS — no framework |
| API | FastAPI (Python 3.11), served via Docker on EC2 |
| Database | PostgreSQL 16 (blog posts, tags, authors, subscribers) |
| Web server | nginx (reverse proxy + static files) |
| CI/CD | GitHub Actions → SSH deploy to EC2 |

---

## Repo layout

```
cloudista/
├── api/              FastAPI backend
│   ├── main.py       App bootstrap, subscriber routes, lifespan
│   ├── blog_routes.py Blog API + server-rendered post pages
│   ├── config.py     Pydantic BaseSettings (all config from env)
│   ├── dependencies.py PostgreSQL connection pool + Depends()
│   └── schemas.py    All Pydantic request/response models
├── blog/             Post source files (*.txt) + import/image tools
├── blog-site/        Blog listing + post pages (HTML/JS)
├── site/             Landing site (index.html, style.css, etc.)
│   └── assets/       Favicons, og-image, webmanifest
├── infra/            nginx config, PostgreSQL schema
├── images/           Post hero images
├── scripts/          Operational one-off tools
└── .github/workflows CI/CD pipelines
```

---

## Development

**Prerequisites:** Docker, Python 3.11, pipenv, Node.js

```bash
# Start local PostgreSQL + API with hot-reload
make dev

# API runs at http://localhost:8000
# Blog at http://localhost:8000/blog/
```

Local DB: `postgresql://cloudista:cloudista_dev@localhost:5433/cloudista`

---

## Common tasks

```bash
make deploy              # Full deploy: site + API + nginx
make api                 # API only (Docker rebuild + restart)
make site                # Static files only
make import              # Import blog/*.txt posts into PostgreSQL
make populate-images     # Fetch Unsplash/Pexels images for posts missing one
make new-post SLUG=x     # Scaffold a new post
make logs                # Tail live API logs
make health              # Hit /api/health on production
make ssh                 # SSH into vabch.org
make db-shell            # psql into the remote blog DB
```

---

## Writing a post

1. `make new-post SLUG=my-post-title` — creates `blog/YYYY-MM-my-post-title.txt`
2. Write the post in Markdown after the `====` separator
3. Add an `Image:` frontmatter field (required — see below)
4. `make import` — imports into local PostgreSQL
5. Open a PR against `main` — lint must pass before merge
6. Merge → auto-deploys to production

**Post frontmatter:**

```
Title: My Post Title
Author: Marie H.
Date: 2026-03-20
Image: https://images.unsplash.com/photo-...?w=900&q=80&fm=webp&auto=format&fit=crop
Tags: kubernetes, devops
============================================================

Content in Markdown...
```

**Finding an image:**

```bash
UNSPLASH_ACCESS_KEY=... PEXELS_ACCESS_KEY=... python3 blog/populate_images.py --slug my-post-title
```

Or trigger the **Populate Post Images** workflow from the Actions tab.

---

## CI/CD

| Workflow | Trigger | What it does |
|---|---|---|
| **Lint** | Push / PR | ruff, yamllint, shellcheck, eslint via reviewdog |
| **Test** | Push / PR | pytest — all API unit tests must pass |
| **Deploy to Production** | Push to `main` / manual | SSH deploy — auto-detects `--api` vs `--site` from changed paths |
| **Populate Post Images** | Manual | Fetches Unsplash/Pexels images for posts missing one |

Branch protection on `main`:
- Direct pushes blocked — PRs required (enforced for all, including admins)
- `Lint / lint` and `Test / test` checks must pass before merge
- Verified (signed) commits required

---

## Environment variables

Loaded by `api/config.py` via Pydantic `BaseSettings`. Set in `/www/cloudista.org/api/.env` on the server (scaffolded by `deploy.sh` on first run):

```bash
# PostgreSQL — blog posts + subscribers
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

# Cloudflare Turnstile (optional — skipped if blank)
TURNSTILE_SECRET=

# SNS Topic ARN for SES bounce/complaint webhook (optional — skips topic validation if blank)
SES_TOPIC_ARN=
```

Missing required variables raise a `ValidationError` at startup with a clear message.

**GitHub Actions secrets:** `SSH_PRIVATE_KEY`, `SSH_HOST`, `SSH_USER`, `UNSPLASH_ACCESS_KEY`, `PEXELS_ACCESS_KEY`, `BLOG_DB_PASSWORD`, `GOOGLE_API_KEY`

---

## Productization roadmap

### Infrastructure & platform
- [x] PostgreSQL schema (posts, tags, authors, subscribers)
- [x] FastAPI backend (Docker, EC2, `--network host`)
- [x] nginx reverse proxy + static file serving
- [x] SSL/TLS via Certbot (auto-renewal)
- [x] Cloudflare in front (real-IP forwarding configured)
- [x] Security headers (CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy)
- [x] `/api/health` endpoint with DB status
- [x] Migrate subscribers from MySQL → PostgreSQL

### CI/CD & quality
- [x] GitHub Actions: lint (ruff, eslint, yamllint, shellcheck via reviewdog)
- [x] GitHub Actions: pytest suite (unit + integration, mocked DB)
- [x] GitHub Actions: auto-deploy on push to `main` (detects `--api` vs `--site`)
- [x] Branch protection: PRs required, lint + test must pass, signed commits enforced
- [x] `make dev` local dev environment (Docker Postgres + uvicorn hot-reload)

### Blog content & UX
- [x] Blog at root URL (`cloudista.org`) — listing + post pages
- [x] Server-rendered post HTML via FastAPI (SEO-friendly)
- [x] Client-side search
- [x] Categories + tags + related posts
- [x] Pagination
- [x] Post revision history and restore
- [x] Post hero images (Unsplash/Pexels via `populate_images.py`)
- [x] WebP images with nginx content negotiation (fallback to original)
- [x] Performance: non-blocking fonts, CLS/LCP fixes
- [x] Open Graph + Twitter card meta tags
- [x] Sitemap at `/sitemap.xml`
- [x] RSS feed at `/feed.xml`
- [x] `robots.txt`

### Subscriber / email
- [x] Subscribe form with Cloudflare Turnstile CAPTCHA
- [x] Rate limiting on `/api/subscribe` (5/min per IP)
- [x] SES verification email (72-hour token expiry)
- [x] Confirmation flow (`/api/confirm/{token}`)
- [x] Unsubscribe link in every email (`/api/unsubscribe/{token}`)
- [x] SES bounce/complaint webhook via SNS
- [x] Verification email copy updated for live blog
- [x] **SES production access** — granted (50k/day, 14/sec; carries over from account-level approval)
- [x] **New-post notification email** — immediate and weekly digest modes; subscriber frequency preferences via one-time link (`/api/preferences/{token}`); GHA workflows on cron

### SEO & discoverability
- [x] Server-rendered post pages (crawlable HTML with title, description, canonical)
- [x] Sitemap + RSS
- [ ] **Per-post OG image** — post pages use the generic `og-image.png`; should use the post's hero image
- [ ] **Google Search Console** — submit sitemap, verify indexing

### Analytics
- [x] Plausible privacy-friendly analytics (all pages, no cookie banner required)

---

## Revenue roadmap (next 3 months)

Goal: reach first revenue by month 3. Strategy: grow organic search traffic → build subscriber list → monetize via sponsorships and a paid tier.

### Month 1 — Audience foundation
- [ ] **Google Search Console** — submit sitemap, verify indexing, monitor impressions
- [ ] **Per-post OG image** — use post hero image for social shares (higher CTR)
- [ ] **Consistent publishing cadence** — 2–3 posts/week targeting long-tail DevOps/cloud keywords
- [ ] **Keyword research** — identify low-competition, high-intent terms (e.g. "kubectl debug cheatsheet", "terraform state locking fix")
- [ ] **Internal linking pass** — link related posts to each other to improve crawl depth and time-on-site
- [ ] **Email list hygiene** — purge unconfirmed subscribers older than 30 days; track open rate as baseline

### Month 2 — Monetization groundwork
- [ ] **Sponsorship page** — audience stats, rate card, contact form; target DevOps SaaS companies (Datadog, Doppler, Cloudflare, Pulumi, etc.)
- [ ] **Carbon Ads or EthicalAds** — low-friction developer-focused ad network; single slot in post sidebar/footer
- [ ] **Affiliate links** — DigitalOcean, Linode/Akamai, AWS (via Amazon Associates) referral links in relevant posts
- [ ] **Subscriber milestone target: 100 confirmed** — use as signal for first outbound sponsorship pitch

### Month 3 — First revenue
- [ ] **First sponsored post or newsletter slot** — flat-fee placement ($150–$500 for a technical blog at this stage)
- [ ] **"Buy me a coffee" / GitHub Sponsors** — low-friction one-time support for readers who find value
- [ ] **Premium content experiment** — one gated deep-dive (e.g. "Production Kubernetes on a Budget: Full Walkthrough") behind an email gate or $5–10 paywall via Gumroad/Lemon Squeezy
- [ ] **Referral program** — "Share with a colleague" CTA in digest emails with a tracked link

### Metrics to track
| Metric | Month 1 target | Month 3 target |
|--------|----------------|----------------|
| Organic search impressions | Baseline | 5,000/mo |
| Confirmed subscribers | 50 | 200 |
| Monthly page views | Baseline | 2,000 |
| Revenue | $0 | First dollar |