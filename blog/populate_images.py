#!/usr/bin/env python3
"""
Populate post images from Unsplash (primary) with Pexels fallback.

For each published post without an image, determines a search query from
the post slug/title, fetches a relevant photo, and stores the CDN URL
(with optimization params) and photographer attribution.

Usage:
    UNSPLASH_ACCESS_KEY=<key> python3 populate_images.py
    UNSPLASH_ACCESS_KEY=<key> PEXELS_ACCESS_KEY=<key> python3 populate_images.py
    UNSPLASH_ACCESS_KEY=<key> python3 populate_images.py --limit 20
    UNSPLASH_ACCESS_KEY=<key> python3 populate_images.py --slug my-post-slug
    UNSPLASH_ACCESS_KEY=<key> python3 populate_images.py --dry-run

Unsplash free tier: 50 requests/hour. When the Unsplash rate limit is hit,
the script falls back to Pexels (200 req/hour) if PEXELS_ACCESS_KEY is set.
If neither is available, waits 65 minutes for Unsplash to reset.

Image URLs:
    Unsplash: ?w=900&q=80&fm=webp&auto=format&fit=crop&crop=entropy
    Pexels:   ?auto=compress&cs=tinysrgb&w=900&fit=crop
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter

import psycopg2
import psycopg2.extras

# ── Config ────────────────────────────────────────────────────────────────────

_DEFAULT_DSN = "postgresql://cloudista:cloudista_dev@localhost:5433/cloudista"
# Set POPULATE_DB_DSN in production; the default is for local dev only.
DB_DSN = os.environ.get("POPULATE_DB_DSN", _DEFAULT_DSN)
UTM               = "utm_source=cloudista&utm_medium=referral"
IMG_PARAMS        = "w=900&q=80&fm=webp&auto=format&fit=crop&crop=entropy"
PEXELS_IMG_PARAMS = "auto=compress&cs=tinysrgb&w=900&fit=crop"

# ── Keyword → search query map ────────────────────────────────────────────────
# Matched against slug + title. First match wins.

KEYWORD_MAP = [
    # Security & reverse engineering
    (r"red.team|pentest|hacker.?one|bug.bounty|exploit|cve",
     "cybersecurity hacker"),
    (r"reverse.engineer|decompil|intercept|ssl.pin|mitm|mitmproxy",
     "reverse engineering code security"),
    (r"secret.leak|incident.response|postmortem|outage|downtime|rca",
     "security breach incident alert"),
    (r"vault|key.protect|encrypt|mtls|tls|cert",
     "encryption key security"),
    (r"auth|oauth|jwt|sso|saml|ldap|forgerock",
     "authentication security login"),
    (r"iam|rbac|access.control|privilege|firewall",
     "security lock access control"),
    (r"fingerprint|biometric|device.id|emulator",
     "mobile device security"),
    (r"akamai|bot.manager|fraud|threatmetrix",
     "cybersecurity protection shield"),

    # Kubernetes & containers
    (r"velero|disaster.recover|dr.pipeline",
     "data center resilience"),
    (r"helm|deploy.*kube|kube.*deploy|pre.helm",
     "software deployment automation"),
    (r"opa|rego|policy.as.code|admission.control|gatekeeper",
     "security policy compliance code"),
    (r"gke|kubernetes|k8s|kubectl|cluster|pod|namespace",
     "server rack data center technology"),
    (r"docker|dockerfile|container.imag|artifact.registr|gcr",
     "software virtualization technology"),

    # CI/CD, pipelines & automation
    (r"jenkins|github.action|ci.cd|pipeline|deploy",
     "software deployment automation workflow"),
    (r"argocd|gitops|terraform.auto.merg",
     "code pipeline automation"),
    (r"ansible|saltstack|puppet|chef|configuration.manag",
     "server automation technology"),
    (r"cron|schedul|job.queue|worker|celery|workflow",
     "scheduled task automation workflow"),
    (r"webhook|event.driven|message.queue|rabbitmq|kafka",
     "event driven system integration"),

    # Infrastructure as code
    (r"terraform|infrastructure.as.code|pulumi",
     "infrastructure code terminal laptop"),
    (r"refactor|monolith|migration|rewrite|legacy",
     "software architecture refactor"),
    (r"api.gateway|proxy|middleware|reverse.proxy",
     "api gateway network technology"),

    # Cloud platforms
    (r"gcp|google.cloud|cloud.sql|cloud.kms|cloud.run|gcs|bigquery",
     "cloud computing data"),
    (r"aws|amazon|ec2|s3|lambda|cloudendure|cloudwatch",
     "AWS cloud computing data center"),
    (r"azure|microsoft.cloud",
     "cloud computing office technology"),
    (r"ibm.cloud|ibm|acadia",
     "enterprise technology business"),

    # Observability & monitoring
    (r"opentelemetry|otel|tracing|jaeger|grafana|prometheus|sensu|nagios",
     "analytics metrics charts server"),
    (r"alert|threshold|pagerduty|on.?call",
     "monitoring alert dashboard"),
    (r"log|observ|metric",
     "server monitoring terminal screen"),

    # Mobile & apps
    (r"android|ios|apk|mobile.app|swift|kotlin",
     "mobile app development smartphone"),

    # Languages & frameworks
    (r"llm|ai.assist|code.migrat|machine.learn",
     "artificial intelligence technology"),
    (r"golang|go.grpc|grpc",
     "programming code abstract"),
    (r"python|flask|fastapi|django",
     "programming code screen laptop"),
    (r"powershell|windows.server|winrm",
     "computer office server technology"),
    (r"ruby|rails",
     "programming code development"),
    (r"javascript|node|react|angular",
     "web development code"),
    (r"bash|shell.script|linux.bastion|cygwin",
     "terminal command line dark"),

    # Databases & storage
    (r"postgres|mysql|database|db.migrat|cloud.sql",
     "database storage server"),
    (r"redis|cache|memcach",
     "speed network technology"),

    # Networking & infrastructure
    (r"netscaler|load.balanc|haproxy|nginx",
     "network traffic infrastructure"),
    (r"dns|vpn|network|firewall",
     "network cable server"),
    (r"orchestrat|reactor",
     "automation conductor technology"),

    # Platforms & practices
    (r"hackathon|civic|community.tech",
     "team hackathon collaboration"),
    (r"chatops|slack|hipchat",
     "team communication collaboration"),
    (r"platform.engineer|sre|devops",
     "software developer laptop workspace"),
    (r"crowdstrike|falcon|edr|endpoint",
     "cybersecurity protection"),
    (r"content.security|csp|xss|owasp",
     "web security browser"),
    (r"backup|restore",
     "data backup storage"),
    (r"vmware|vsphere|virtual",
     "server room hardware"),
    (r"grpc|protobuf|microservice|service.mesh",
     "distributed systems architecture"),
    (r"ipam|solarwind|network.manag",
     "network infrastructure management"),
    (r"custom.command|slash.command|productivity|workflow.automat",
     "productivity workflow automation"),

    # Text editors & IDEs
    (r"vim|neovim|emacs|text.editor|code.editor|vundle|youcomplet",
     "code editor terminal dark screen"),

    # CMS / web / older posts
    (r"drupal|wordpress|cms|cpanel|plugin|tinymce|htmlpurifier",
     "web browser laptop development"),
    (r"trello|jira|project.manag|ticket|board",
     "project management collaboration board"),
    (r"bootstrap|css|html|frontend|scroll|center|rotat",
     "web design frontend development"),
    (r"craigslist|scraping|parse|python.scrape",
     "web scraping data programming"),
    (r"excel|spreadsheet|csv|phpexcel|import",
     "data spreadsheet analytics business"),
    (r"linkedin|social|profile",
     "professional networking business laptop"),
    (r"tesseract|ocr|image.recogni|vision",
     "document scanning text recognition"),
    (r"fuzz|test|selenium|unit.test|integration",
     "software testing quality assurance"),
    (r"generic|interface|pattern|design.pattern",
     "software architecture abstract code"),
    (r"perl|parsing|log.pars|regex",
     "code terminal parsing data"),
    (r"spam|email|notif|mailchimp|ses|newsletter",
     "email communication technology"),
    (r"wifi|smart.home|iot|garage|raspberry",
     "smart home technology device"),
    (r"bamboo|rally|atlassian",
     "team software development agile"),
    (r"angular|datatab|ajax|frontend.frame",
     "web development javascript framework"),
    (r"ocr|business.card|scan|vision",
     "document scanning technology"),
    (r"powershell|windows|winrm|fleet",
     "computer office server technology"),
    (r"go.generic|go.embed|go.module|go.context|go.fuzz|go.1",
     "programming code abstract"),
]

DEFAULT_QUERY = "technology server infrastructure"

# ── Tag / category slug → search query (used when KEYWORD_MAP has no match) ──
TAG_QUERY_MAP = {
    "kubernetes":   "server rack data center technology",
    "gcp":          "google cloud computing data center",
    "aws":          "AWS cloud computing data center",
    "azure":        "cloud computing office technology",
    "docker":       "software container virtualization",
    "terraform":    "devops automation workflow code",
    "security":     "security lock access control shield",
    "iam":          "security identity access control",
    "python":       "python programming code laptop",
    "golang":       "programming code abstract technology",
    "javascript":   "web development code browser",
    "monitoring":   "analytics metrics charts server screen",
    "database":     "database storage server racks",
    "postgresql":   "database storage server",
    "mysql":        "database server storage",
    "redis":        "speed cache network technology",
    "linux":        "terminal command line server dark",
    "bash":         "terminal command line script",
    "nginx":        "web server network traffic",
    "cicd":         "automation pipeline continuous delivery",
    "serverless":   "cloud function computing abstract",
    "saltstack":    "server automation configuration management",
    "ansible":      "server automation infrastructure",
    "service-mesh": "distributed systems microservices network",
    "ibm-cloud":    "enterprise technology business server",
    "chatops":      "team communication collaboration chat",
    "gitops":       "code pipeline git automation",
    "devops":       "engineering team technology collaboration",
    "web":          "web development browser laptop",
    "drupal":       "content management website development",
    "wordpress":    "website blogging content management",
    "php":          "web programming code development",
    "helm":         "kubernetes deployment package manager",
    "gke":          "google kubernetes cloud cluster",
    "aks":          "azure kubernetes cloud cluster",
    "lambda":       "serverless function cloud computing",
    "prometheus":   "monitoring metrics charts dashboard",
    "grafana":      "analytics dashboard visualization charts",
    "ec2":          "cloud server computing virtual machine",
    "s3":           "cloud storage data bucket",
}

# ── Stop words for keyword extraction ─────────────────────────────────────────
# Words filtered out before building an image search query from post content.

_STOP_WORDS = {
    # Common English
    "about", "above", "after", "again", "against", "all", "also", "although",
    "always", "and", "another", "any", "are", "around", "back", "because",
    "been", "before", "being", "between", "both", "but", "can", "could",
    "did", "does", "during", "each", "either", "else", "even", "every",
    "for", "from", "further", "get", "gets", "give", "given", "got", "had",
    "has", "have", "having", "her", "here", "him", "his", "how", "however",
    "into", "is", "it", "its", "itself", "just", "may", "me", "might",
    "more", "most", "much", "must", "my", "need", "needs", "never", "next",
    "not", "now", "of", "off", "often", "on", "once", "only", "or", "other",
    "our", "out", "over", "own", "per", "rather", "same", "she", "since",
    "so", "some", "still", "such", "than", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "those", "though", "through",
    "to", "too", "under", "until", "up", "us", "used", "very", "was", "we",
    "were", "what", "when", "where", "which", "while", "who", "will", "with",
    "within", "without", "would", "you", "your",
    # Generic technical words — too broad for image search
    "added", "adding", "already", "approach", "available", "build", "builds",
    "call", "calls", "caused", "change", "changes", "check", "code", "command",
    "commit", "config", "correct", "create", "data", "default", "deploy",
    "detail", "didn't", "different", "doesn't", "done", "doesn", "error",
    "errors", "example", "existing", "failed", "file", "files", "finally",
    "fixed", "follow", "function", "handle", "header", "here", "install",
    "instead", "issue", "line", "list", "local", "make", "makes", "making",
    "means", "message", "missing", "module", "name", "number", "option",
    "output", "pass", "path", "point", "problem", "process", "read",
    "remove", "request", "requires", "response", "result", "return", "right",
    "running", "script", "set", "show", "since", "something", "specific",
    "start", "string", "support", "syntax", "test", "tests", "time", "type",
    "update", "using", "value", "version", "want", "well", "work", "works",
    "write", "wrote", "went", "step", "steps", "look", "looks", "like",
    "mean", "case", "note", "lets", "take", "took", "side", "side", "way",
    "ways", "thing", "things", "actually", "basically", "simply", "pretty",
    "found", "find", "tried", "trying", "came", "come", "end", "ends",
    "part", "parts", "rest", "lot", "lots", "bit", "bits", "run", "runs",
    "patch", "repo", "tag", "tags", "yes", "no", "okay", "ok", "see",
}


def _extract_keywords(content_md: str, n: int = 4) -> list[str]:
    """Extract the top N meaningful keywords from markdown post content."""
    # Strip fenced code blocks
    text = re.sub(r"```[\s\S]*?```", " ", content_md)
    # Strip inline code and backtick spans
    text = re.sub(r"`[^`]+`", " ", text)
    # Strip URLs
    text = re.sub(r"https?://\S+", " ", text)
    # Strip markdown syntax characters
    text = re.sub(r"[#*\[\]()>|_~=\-]+", " ", text)
    # Lowercase and extract words of 5+ characters
    words = re.findall(r"[a-z]{5,}", text.lower())
    words = [w for w in words if w not in _STOP_WORDS]
    if not words:
        return []
    counts = Counter(words)
    return [w for w, _ in counts.most_common(n)]


# ── Helpers ───────────────────────────────────────────────────────────────────

def search_query_for(slug: str, title: str, content_md: str = "",
                     tags=None, categories=None) -> str:
    tag_str = " ".join(tags or [])
    cat_str = " ".join(categories or [])
    combined = f"{slug} {title} {tag_str} {cat_str}".lower()
    for pattern, query in KEYWORD_MAP:
        if re.search(pattern, combined):
            return query
    # No KEYWORD_MAP match — try direct tag/category lookup
    for slug_key in (tags or []) + (categories or []):
        if slug_key in TAG_QUERY_MAP:
            return TAG_QUERY_MAP[slug_key]
    # Fall back to content keyword extraction
    if content_md:
        keywords = _extract_keywords(content_md, n=4)
        if keywords:
            return " ".join(keywords[:3])
    return DEFAULT_QUERY


def _photo_base_url(image_url: str) -> str:
    """Extract the base URL (before ?) for dedup keying."""
    return image_url.split("?")[0] if image_url else ""


class RateLimitError(Exception):
    """Raised when a photo API returns a rate-limit response."""


def unsplash_fetch(query: str, access_key: str, used_urls: set) -> dict | None:
    """Search Unsplash and return the first landscape result not already in use.
    Raises RateLimitError on HTTP 403."""
    params = urllib.parse.urlencode({
        "query":          query,
        "per_page":       10,
        "orientation":    "landscape",
        "content_filter": "high",
    })
    url = f"https://api.unsplash.com/search/photos?{params}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Client-ID {access_key}",
        "Accept-Version": "v1",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            # Warn proactively when nearing the limit
            remaining = resp.headers.get("X-Ratelimit-Remaining", "")
            if remaining and int(remaining) <= 5:
                print(f"    ⚠ Only {remaining} Unsplash requests remaining this hour", file=sys.stderr)
            data = json.loads(resp.read())
            results = data.get("results", [])
            if not results:
                return None
            # Sort by downloads descending, pick first not already used
            ranked = sorted(results, key=lambda p: p.get("downloads", 0), reverse=True)
            for photo in ranked:
                base = _photo_base_url(photo["urls"]["raw"])
                if base not in used_urls:
                    return photo
            # All results already used — return None so caller can retry
            print(f"    ⚠ All results for {query!r} already in use", file=sys.stderr)
            return None
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise RateLimitError("Unsplash rate limit reached (403)")
        print(f"    ✗ Unsplash API error: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"    ✗ Unsplash API error: {e}", file=sys.stderr)
        return None


def pexels_fetch(query: str, access_key: str, used_urls: set) -> dict | None:
    """Search Pexels and return the first landscape result not already in use.
    Raises RateLimitError on HTTP 429."""
    params = urllib.parse.urlencode({
        "query":       query,
        "per_page":    10,
        "orientation": "landscape",
    })
    url = f"https://api.pexels.com/v1/search?{params}"
    req = urllib.request.Request(url, headers={
        "Authorization": access_key,
        "User-Agent": "Mozilla/5.0 (compatible; cloudista-image-bot/1.0)",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            remaining = resp.headers.get("X-Ratelimit-Remaining", "")
            if remaining and int(remaining) <= 5:
                print(f"    ⚠ Only {remaining} Pexels requests remaining", file=sys.stderr)
            data = json.loads(resp.read())
            photos = data.get("photos", [])
            if not photos:
                return None
            for photo in photos:
                base = _photo_base_url(photo["src"]["large2x"])
                if base not in used_urls:
                    return photo
            print(f"    ⚠ All Pexels results for {query!r} already in use", file=sys.stderr)
            return None
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimitError("Pexels rate limit reached (429)")
        print(f"    ✗ Pexels API error: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"    ✗ Pexels API error: {e}", file=sys.stderr)
        return None




def build_image_url(photo: dict) -> str:
    raw = photo["urls"]["raw"]
    # Strip any existing params Unsplash may have appended
    base = raw.split("?")[0]
    return f"{base}?{IMG_PARAMS}"


def build_pexels_image_url(photo: dict) -> str:
    base = photo["src"]["large2x"].split("?")[0]
    return f"{base}?{PEXELS_IMG_PARAMS}"


def build_credit(photo: dict) -> str:
    user  = photo["user"]
    name  = user["name"]
    ulink = user["links"]["html"]
    return (
        f'Photo by <a href="{ulink}?{UTM}" target="_blank" rel="noopener">{name}</a>'
        f' on <a href="https://unsplash.com/?{UTM}" target="_blank" rel="noopener">Unsplash</a>'
    )


def build_pexels_credit(photo: dict) -> str:
    name  = photo["photographer"]
    plink = photo["photographer_url"]
    return (
        f'Photo by <a href="{plink}" target="_blank" rel="noopener">{name}</a>'
        f' on <a href="https://www.pexels.com" target="_blank" rel="noopener">Pexels</a>'
    )


# ── Fetch with fallback ───────────────────────────────────────────────────────

def _fetch_with_fallback(
    query: str,
    access_key: str,
    pexels_key: str,
    used_urls: set,
    content: str = "",
) -> tuple[dict, str] | tuple[None, None]:
    """
    Try Unsplash first, then Pexels, with content-keyword retries.
    Returns (photo_dict, provider_name) or (None, None) if nothing found.
    Handles RateLimitError internally — waits for Unsplash reset when no Pexels key.
    """
    def _try_unsplash(q: str) -> dict | None:
        try:
            return unsplash_fetch(q, access_key, used_urls)
        except RateLimitError:
            raise

    def _try_pexels(q: str) -> dict | None:
        if not pexels_key:
            return None
        try:
            return pexels_fetch(q, pexels_key, used_urls)
        except RateLimitError:
            raise

    def _attempt(q: str) -> tuple[dict, str] | tuple[None, None]:
        photo = _try_unsplash(q)
        if photo is not None:
            return photo, "unsplash"
        photo = _try_pexels(q)
        if photo is not None:
            return photo, "pexels"
        return None, None

    # Primary query
    try:
        result, provider = _attempt(query)
    except RateLimitError:
        if pexels_key:
            print("    ⚠ Unsplash rate limit — trying Pexels...")
            try:
                photo = pexels_fetch(query, pexels_key, used_urls)
                if photo is not None:
                    return photo, "pexels"
            except RateLimitError:
                print("           ✗ Both Unsplash and Pexels rate-limited — skipping", file=sys.stderr)
                return None, None
        else:
            wait = 65 * 60
            print(f"\n  ✗ Unsplash rate limit hit — pausing {wait // 60} min for hourly reset...\n")
            time.sleep(wait)
            try:
                result, provider = _attempt(query)
            except RateLimitError:
                print("           ✗ Still rate-limited after wait — skipping", file=sys.stderr)
                return None, None
    else:
        if result is not None:
            return result, provider

    # Retry with content keywords
    if content:
        kws = _extract_keywords(content, n=6)
        if kws:
            alt_query = " ".join(kws[:4])
            print(f"           ↩ retrying with keyword query: {alt_query!r}")
            try:
                result, provider = _attempt(alt_query)
                if result is not None:
                    return result, provider
            except RateLimitError:
                pass

            for prefix in ("devops", "platform engineering"):
                prefixed = f"{prefix} {alt_query}"
                print(f"           ↩ retrying with: {prefixed!r}")
                try:
                    result, provider = _attempt(prefixed)
                    if result is not None:
                        return result, provider
                except RateLimitError:
                    pass

    return None, None


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Populate post images from Unsplash")
    parser.add_argument("--limit",          type=int, default=0,  help="Max posts to process (0 = all)")
    parser.add_argument("--slug",           type=str, default="", help="Process a single post by slug")
    parser.add_argument("--dry-run",        action="store_true",  help="Print queries without updating DB")
    parser.add_argument("--refetch",        action="store_true",  help="Re-fetch images even if post already has one")
    parser.add_argument(
        "--fix-duplicates", action="store_true",
        help="Clear duplicate image URLs and re-fetch unique ones",
    )
    args = parser.parse_args()

    access_key = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
    if not access_key:
        print("Error: UNSPLASH_ACCESS_KEY environment variable not set.", file=sys.stderr)
        print("  Get a free key at https://unsplash.com/developers", file=sys.stderr)
        sys.exit(1)
    pexels_key = os.environ.get("PEXELS_ACCESS_KEY", "").strip()
    if pexels_key:
        print("Pexels fallback enabled.")

    conn = psycopg2.connect(DB_DSN, cursor_factory=psycopg2.extras.RealDictCursor)
    cur  = conn.cursor()

    # ── Load all currently-used image base URLs for dedup ─────────────────────
    cur.execute("SELECT image_url FROM posts WHERE image_url IS NOT NULL")
    used_urls: set = set()
    for row in cur.fetchall():
        base = _photo_base_url(row["image_url"])
        if base:
            used_urls.add(base)
    print(f"Loaded {len(used_urls)} existing photo URLs for dedup.\n")

    # ── Pre-fetch tags and categories for all posts ───────────────────────────
    cur.execute("""
        SELECT pt.post_id, t.slug AS tag_slug
        FROM   post_tags pt JOIN tags t ON t.id = pt.tag_id
    """)
    post_tags_map = {}
    for row in cur.fetchall():
        post_tags_map.setdefault(row["post_id"], []).append(row["tag_slug"])

    cur.execute("""
        SELECT pc.post_id, c.slug AS cat_slug
        FROM   post_categories pc JOIN categories c ON c.id = pc.category_id
    """)
    post_cats_map = {}
    for row in cur.fetchall():
        post_cats_map.setdefault(row["post_id"], []).append(row["cat_slug"])

    # ── Select which posts to process ─────────────────────────────────────────
    if args.fix_duplicates:
        # Find posts sharing an image_url with another post; keep the oldest
        # (lowest id) per URL, clear the rest so they get re-fetched uniquely.
        cur.execute(
            """
            SELECT id, slug, title, content_md, image_url
            FROM   posts
            WHERE  status = 'published'
              AND  image_url LIKE '%images.unsplash.com%'
              AND  id NOT IN (
                SELECT MIN(id)
                FROM   posts
                WHERE  image_url IS NOT NULL
                GROUP  BY image_url
              )
            ORDER  BY published_at DESC
            """
        )
        to_clear = cur.fetchall()
        if not args.dry_run:
            ids = [p["id"] for p in to_clear]
            if ids:
                cur.execute(
                    "UPDATE posts SET image_url = NULL, image_credit = NULL, updated_at = NOW() WHERE id = ANY(%s)",
                    (ids,),
                )
                conn.commit()
            print(f"Cleared {len(to_clear)} duplicate image URLs — re-fetching…\n")
        else:
            print(f"Would clear {len(to_clear)} duplicate image URLs (dry run).\n")
        posts = to_clear

    elif args.slug:
        cur.execute(
            "SELECT id, slug, title, content_md FROM posts WHERE slug = %s AND status = 'published'",
            (args.slug,),
        )
        posts = cur.fetchall()
    elif args.refetch:
        cur.execute(
            "SELECT id, slug, title, content_md FROM posts WHERE status = 'published' ORDER BY published_at DESC"
        )
        posts = cur.fetchall()
    else:
        cur.execute(
            "SELECT id, slug, title, content_md FROM posts"
            " WHERE status = 'published' AND image_url IS NULL ORDER BY published_at DESC"
        )
        posts = cur.fetchall()

    if args.limit:
        posts = posts[:args.limit]

    total = len(posts)
    print(f"Processing {total} posts{' (dry run)' if args.dry_run else ''}…\n")

    updated = 0
    errors  = 0

    for i, post in enumerate(posts, 1):
        slug       = post["slug"]
        title      = post["title"]
        content    = post.get("content_md") or ""
        post_id    = post["id"]
        tags       = post_tags_map.get(post_id, [])
        categories = post_cats_map.get(post_id, [])
        query      = search_query_for(slug, title, content, tags=tags, categories=categories)

        print(f"  [{i}/{total}] {slug}")
        print(f"           query: {query!r}")

        if args.dry_run:
            print()
            continue

        photo, provider = _fetch_with_fallback(
            query, access_key, pexels_key, used_urls, content
        )

        if not photo:
            print("           ✗ No results — skipping")
            errors += 1
        else:
            if provider == "pexels":
                img_url = build_pexels_image_url(photo)
                credit = build_pexels_credit(photo)
                print(f"           ✓ [pexels] {photo['id']} by {photo['photographer']}")
            else:
                img_url = build_image_url(photo)
                credit = build_credit(photo)
                print(f"           ✓ [unsplash] {photo['id']} by {photo['user']['name']}")

            cur.execute(
                "UPDATE posts SET image_url = %s, image_credit = %s, updated_at = NOW() WHERE id = %s",
                (img_url, credit, post["id"]),
            )
            conn.commit()  # commit each row so progress is saved across rate-limit waits
            # Mark this photo as used so subsequent posts won't pick it
            base = _photo_base_url(img_url)
            if base:
                used_urls.add(base)
            updated += 1

        # Unsplash free tier: 50 req/hour. 1.5s delay = ~40 req/min, well under limit.
        if i < total:
            if i % 45 == 0:
                print("\n  ⚠  Pausing 90s to respect Unsplash rate limit (50 req/hr)…\n")
                time.sleep(90)
            else:
                time.sleep(1.5)

    cur.close()
    conn.close()

    print(f"\n{'─'*50}")
    print(f"Updated : {updated}")
    print(f"Errors  : {errors}")
    print(f"Skipped : {total - updated - errors}")


if __name__ == "__main__":
    main()
