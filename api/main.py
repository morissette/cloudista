"""
Cloudista API
-------------
POST /api/subscribe              – register an email; sends a verification email via SES
GET  /api/confirm/{token}        – confirm subscription; redirects to site with status param
GET  /api/unsubscribe/{token}    – unsubscribe; redirects to site with status param
POST /api/ses-webhook            – SNS bounce/complaint handler (internal; not in docs)
GET  /api/health                 – liveness probe (validates DB connectivity)
"""

import asyncio
import base64
import contextvars
import json
import logging
import re
import secrets
import time
import urllib.parse
import urllib.request
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum

import asyncpg
import boto3
from blog_routes import _counter_post_views
from blog_routes import html_router as blog_html_router
from blog_routes import router as blog_router
from botocore.exceptions import BotoCoreError, ClientError
from config import settings
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate
from dependencies import _real_ip, close_pool, get_pg_conn, init_pool, limiter
from email_template import build_contact_email, build_verification_email
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from prometheus_client import Gauge
from prometheus_fastapi_instrumentator import Instrumentator
from schemas import ContactIn, HealthOut, MessageOut, PreferencesIn, SubscribeIn
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# ---------------------------------------------------------------------------
# Logging — inject request_id into every log record via a context var + filter
# ---------------------------------------------------------------------------
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        return True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(request_id)s] %(message)s",
)
logging.getLogger().addFilter(_RequestIdFilter())
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_TOKEN_TTL = timedelta(hours=72)
_PREFS_TOKEN_TTL = timedelta(days=365)

# SNS cert cache: maps URL → (cert_pem, fetch_timestamp). Certs expire after 24h
# so stale certs don't persist if AWS rotates signing keys.
_SNS_CERT_CACHE: dict[str, tuple[bytes, float]] = {}
_SNS_CERT_TTL = 86_400  # 24 hours in seconds


def _mask_email(email: str) -> str:
    """Return a partially-masked email for safe logging (e.g. jo***@example.com)."""
    at = email.find("@")
    if at <= 0:
        return "***"
    return email[:min(2, at)] + "***" + email[at:]

# SNS field order for canonical string construction (per AWS spec)
_SNS_NOTIFICATION_FIELDS = ["Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"]
_SNS_SUBSCRIPTION_FIELDS = ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"]


# ---------------------------------------------------------------------------
# Turnstile result enum
# ---------------------------------------------------------------------------
class TurnstileResult(Enum):
    VALID = "valid"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
async def _seed_post_view_metrics() -> None:
    """Seed Prometheus post-view metrics from DB so counters survive restarts."""
    from dependencies import _pg_pool as pool
    async with pool.acquire() as conn:
        # Option A: pre-seed the per-request counter so rate() is continuous
        rows = await conn.fetch(
            """
            SELECT p.slug, pv.country, pv.is_bot, SUM(pv.view_count)::bigint AS total
            FROM post_views pv
            JOIN posts p ON p.id = pv.post_id
            GROUP BY p.slug, pv.country, pv.is_bot
            """
        )
        for row in rows:
            _counter_post_views.labels(
                slug=row["slug"],
                country=row["country"],
                is_bot=str(row["is_bot"]),
            ).inc(row["total"])

        # Option B: set all-time human view gauge per slug
        await _refresh_post_views_db_gauge(conn)


async def _refresh_post_views_db_gauge(conn) -> None:
    """Update the all-time human view gauge from the DB."""
    rows = await conn.fetch(
        """
        SELECT p.slug, SUM(pv.view_count)::bigint AS total
        FROM post_views pv
        JOIN posts p ON p.id = pv.post_id
        WHERE pv.is_bot = false
        GROUP BY p.slug
        """
    )
    for row in rows:
        _gauge_post_views_db.labels(slug=row["slug"]).set(row["total"])


async def _post_views_gauge_loop() -> None:
    """Refresh the all-time post views gauge every 60 seconds."""
    from dependencies import _pg_pool as pool
    while True:
        await asyncio.sleep(60)
        try:
            async with pool.acquire() as conn:
                await _refresh_post_views_db_gauge(conn)
        except Exception as exc:
            log.warning("post views gauge refresh failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    try:
        await _seed_post_view_metrics()
    except Exception as exc:
        log.warning("post view metric seeding failed: %s", exc)
    task = asyncio.create_task(_post_views_gauge_loop())
    yield
    task.cancel()
    await close_pool()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Cloudista API", docs_url=None, redoc_url=None, lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(blog_router)
app.include_router(blog_html_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.site_url,
        f"https://www.{settings.site_url.removeprefix('https://')}",
        "null",  # file:// origin for local admin tools
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Key"],
    max_age=3600,
)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/metrics"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# Custom gauges — updated by background tasks or on health checks
_gauge_subscribers = Gauge(
    "cloudista_subscribers_total",
    "Total number of confirmed email subscribers",
)
_gauge_posts_published = Gauge(
    "cloudista_posts_published_total",
    "Number of published blog posts",
)
_gauge_posts_unlisted = Gauge(
    "cloudista_posts_unlisted_total",
    "Number of unlisted blog posts",
)
_gauge_posts_total = Gauge(
    "cloudista_posts_total",
    "Total number of blog posts (all statuses)",
)
_gauge_post_views_db = Gauge(
    "cloudista_post_views_db_total",
    "All-time human post view count from DB by slug",
    ["slug"],
)

# boto3 picks up credentials from the EC2 instance's IAM role automatically.
_ses = boto3.client("ses", region_name=settings.aws_region)


# ---------------------------------------------------------------------------
# Request-ID middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    raw = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    # Strip control characters to prevent CRLF header injection
    req_id = re.sub(r"[^\x20-\x7E]", "", raw)[:64] or str(uuid.uuid4())
    request.state.request_id = req_id
    # Propagate into log records for the duration of this request
    token = _request_id_var.set(req_id)
    try:
        response = await call_next(request)
    finally:
        _request_id_var.reset(token)
    response.headers["X-Request-ID"] = req_id
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token() -> str:
    return secrets.token_urlsafe(32)


def _verify_turnstile_sync(token: str, ip: str) -> TurnstileResult:
    params: dict = {"secret": settings.turnstile_secret, "response": token}
    # Only include remoteip when we have a real IP — Cloudflare rejects non-IP values
    if ip and ip != "unknown":
        params["remoteip"] = ip
    payload = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=payload,
            timeout=5,
        ) as resp:
            data = json.loads(resp.read())
        return TurnstileResult.VALID if data.get("success") else TurnstileResult.INVALID
    except Exception as exc:
        log.warning("Turnstile verify failed (fail open): %s", exc)
        return TurnstileResult.UNAVAILABLE


async def _verify_turnstile(token: str, ip: str) -> TurnstileResult:
    return await asyncio.to_thread(_verify_turnstile_sync, token, ip)


def _send_verification(email: str, token: str, prefs_token: str = "") -> None:
    """
    Send a verification email via AWS SES.
    Raises on failure so the caller can decide whether to propagate.
    """
    confirm_url = f"{settings.confirm_base_url}/{token}"
    unsubscribe_url = f"{settings.site_url}/api/unsubscribe/{token}"
    prefs_url = f"{settings.site_url}/api/preferences/{prefs_token}" if prefs_token else ""
    subject, html, text = build_verification_email(confirm_url, unsubscribe_url, prefs_url)

    _ses.send_email(
        Source=settings.from_email,
        Destination={"ToAddresses": [email]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Html": {"Data": html, "Charset": "UTF-8"},
                "Text": {"Data": text, "Charset": "UTF-8"},
            },
        },
    )
    log.info("Verification email sent → %s", _mask_email(email))


async def _try_send_verification(email: str, token: str, prefs_token: str = "") -> None:
    """Send verification email; log but don't raise on SES failure."""
    try:
        await asyncio.to_thread(_send_verification, email, token, prefs_token)
    except (BotoCoreError, ClientError) as exc:
        log.error("SES send failed for %s: %s", _mask_email(email), exc)


def _sns_canonical_string(body: dict) -> str:
    """Build the canonical string for SNS signature verification (per AWS spec)."""
    msg_type = body.get("Type", "")
    if msg_type == "Notification":
        fields = _SNS_NOTIFICATION_FIELDS
    elif msg_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
        fields = _SNS_SUBSCRIPTION_FIELDS
    else:
        return ""
    return "".join(f"{f}\n{body[f]}\n" for f in fields if f in body)


def _verify_sns_signature(body: dict) -> bool:
    """
    Verify an SNS message signature using the certificate published by AWS.

    Steps:
    1. Validate SigningCertURL is https://*.sns.*.amazonaws.com (prevents SSRF)
    2. Fetch and cache the signing certificate
    3. Verify RSA-SHA1 signature over the canonical string
    """
    cert_url = body.get("SigningCertURL", "")
    parsed = urllib.parse.urlparse(cert_url)

    # Strict hostname validation — must be exactly sns.<region>.amazonaws.com
    if parsed.scheme != "https":
        log.warning("SNS cert URL is not HTTPS: %s", cert_url)
        return False
    if not re.fullmatch(r"sns\.[a-z0-9-]+\.amazonaws\.com", parsed.hostname or ""):
        log.warning("SNS cert URL hostname failed validation: %s", parsed.hostname)
        return False

    canonical = _sns_canonical_string(body)
    if not canonical:
        return False

    cached = _SNS_CERT_CACHE.get(cert_url)
    if cached is not None and time.time() - cached[1] < _SNS_CERT_TTL:
        cert_pem = cached[0]
    else:
        try:
            with urllib.request.urlopen(cert_url, timeout=5) as resp:
                cert_pem = resp.read()
            _SNS_CERT_CACHE[cert_url] = (cert_pem, time.time())
        except Exception as exc:
            log.warning("SNS cert fetch failed: %s", exc)
            return False

    try:
        cert = load_pem_x509_certificate(cert_pem)
        sig = base64.b64decode(body.get("Signature", ""))
        cert.public_key().verify(sig, canonical.encode("utf-8"), padding.PKCS1v15(), hashes.SHA1())
        return True
    except Exception as exc:
        log.warning("SNS signature verification failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Helpers — HTML responses
# ---------------------------------------------------------------------------

def _prefs_html_response(email: str, frequency: str, token: str, saved: str = "", error: str = "") -> Response:
    """Render the subscriber preferences HTML page."""
    from fastapi.responses import HTMLResponse
    site = settings.site_url

    weekly_active = "background:#2563eb;color:#fff;" if frequency == "weekly" else "background:#f1f5f9;color:#0f172a;"
    immediate_active = (
        "background:#2563eb;color:#fff;" if frequency == "immediate"
        else "background:#f1f5f9;color:#0f172a;"
    )

    saved_html = '<p style="color:#16a34a;font-weight:600;margin:0 0 16px;">✓ Preferences saved.</p>' if saved else ""
    error_html = f'<p style="color:#dc2626;margin:0 0 16px;">{error}</p>' if error else ""
    form_html = "" if error else f"""
      <form method="post" style="margin:0;">
        <p style="margin:0 0 12px;font-size:14px;color:#64748b;">How often would you like to hear from us?</p>
        <div style="display:flex;gap:10px;margin-bottom:24px;">
          <button name="frequency" value="weekly"
                  style="flex:1;padding:12px;border-radius:8px;border:1.5px solid #2563eb;
                         cursor:pointer;font-size:14px;font-weight:600;{weekly_active}">
            Weekly digest
          </button>
          <button name="frequency" value="immediate"
                  style="flex:1;padding:12px;border-radius:8px;border:1.5px solid #2563eb;
                         cursor:pointer;font-size:14px;font-weight:600;{immediate_active}">
            Every new post
          </button>
        </div>
      </form>
      <p style="margin:0;font-size:12px;color:#94a3b8;">
        To unsubscribe entirely, <a href="{site}/?unsubscribe=1" style="color:#64748b;">visit cloudista.org</a>
        and use the unsubscribe link from any email.
      </p>
    """

    masked = email[:2] + "***" + email[email.find("@"):] if "@" in email else ""
    title_text = "Email preferences" if not error else "Link not found"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Email preferences — Cloudista</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f1f5f9;min-height:100vh;">
    <tr>
      <td align="center" valign="top" style="padding:48px 16px;">
        <table cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:480px;">
          <tr>
            <td style="border-radius:14px 14px 0 0;
                       background:linear-gradient(135deg,#2563eb 0%,#4f46e5 50%,#7c3aed 100%);
                       padding:28px 36px;text-align:center;">
              <a href="{site}"
                 style="text-decoration:none;color:#fff;font-size:18px;
                        font-weight:800;letter-spacing:-0.03em;">&#9729; Cloudista</a>
            </td>
          </tr>
          <tr>
            <td style="background:#fff;padding:36px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">
              <h1 style="margin:0 0 8px;font-size:22px;font-weight:800;
                         color:#0f172a;letter-spacing:-0.03em;">{title_text}</h1>
              {"" if error else f'<p style="margin:0 0 20px;font-size:14px;color:#64748b;">{masked}</p>'}
              {saved_html}{error_html}{form_html}
            </td>
          </tr>
          <tr>
            <td style="background:#f8fafc;border:1px solid #e2e8f0;
                       border-top:none;border-radius:0 0 14px 14px;
                       padding:16px 36px;text-align:center;">
              <p style="margin:0;font-size:12px;color:#94a3b8;">&copy; 2026 Cloudista</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthOut)
async def health():
    """Liveness probe. Always returns 200; DB connectivity reported in body."""
    from dependencies import _pg_pool  # noqa: PLC0415 — intentional late import to avoid circular

    db_ok = True
    db_error = None
    try:
        if _pg_pool is None:
            raise RuntimeError("pool not initialised")
        async with _pg_pool.acquire(timeout=2.0) as conn:
            await conn.fetchval("SELECT 1")
            # Refresh Prometheus gauges while we have a live connection
            try:
                sub_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM subscribers WHERE status = 'confirmed'"
                )
                post_counts = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'published') AS published,
                        COUNT(*) FILTER (WHERE status = 'unlisted')  AS unlisted,
                        COUNT(*)                                      AS total
                    FROM posts
                    """
                )
                if sub_count is not None:
                    _gauge_subscribers.set(sub_count)
                if post_counts is not None:
                    _gauge_posts_published.set(post_counts["published"])
                    _gauge_posts_unlisted.set(post_counts["unlisted"])
                    _gauge_posts_total.set(post_counts["total"])
            except Exception:
                pass  # gauge refresh is best-effort; don't fail health check
    except Exception as exc:
        log.warning("DB ping failed: %s", exc)
        db_ok = False
        db_error = "Unavailable"
    return HealthOut(
        status="ok",
        db="ok" if db_ok else "unavailable",
        db_error=db_error,
    )


@app.post("/api/subscribe", response_model=MessageOut, status_code=201)
@limiter.limit("5/minute")
async def subscribe(
    request: Request,
    body: SubscribeIn,
    response: Response,
    conn: asyncpg.Connection = Depends(get_pg_conn),
):
    """
    Register an email address for launch notifications.

    Flow:
    1. Insert row with status='pending'
    2. Send verification email via SES
    3. User clicks link → GET /api/confirm/{token}
    """
    ip = _real_ip(request)
    ua = request.headers.get("User-Agent", "")[:500]

    if body.cf_turnstile_token:
        if not settings.turnstile_secret:
            log.warning("Turnstile token received but TURNSTILE_SECRET not configured — skipping")
        else:
            result = await _verify_turnstile(body.cf_turnstile_token, ip)
            if result is TurnstileResult.INVALID:
                raise HTTPException(status_code=400, detail="CAPTCHA verification failed.")

    send_token: str | None = None
    send_prefs_token: str = ""
    resend_msg: str | None = None  # None signals new insert (→ 201)

    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, status, token, token_expires_at, prefs_token FROM subscribers WHERE email = $1 LIMIT 1",
                body.email,
            )

            if row:
                if row["status"] == "confirmed":
                    response.status_code = 200
                    return MessageOut(message="Already confirmed.")

                if row["status"] == "unsubscribed":
                    t = _make_token()
                    pt = _make_token()
                    await conn.execute(
                        "UPDATE subscribers SET status='pending', token=$1, token_expires_at=$2,"
                        " confirmed_at=NULL, unsubscribed_at=NULL,"
                        " prefs_token=$3, prefs_token_expires_at=$4 WHERE id=$5",
                        t,
                        datetime.now(timezone.utc) + _TOKEN_TTL,
                        pt,
                        datetime.now(timezone.utc) + _PREFS_TOKEN_TTL,
                        row["id"],
                    )
                    send_token = t
                    send_prefs_token = pt
                    resend_msg = "Re-subscribed — check your email."
                else:
                    # pending — always rotate token on resend so old links are invalidated
                    t = _make_token()
                    pt = _make_token()
                    await conn.execute(
                        "UPDATE subscribers SET token=$1, token_expires_at=$2,"
                        " prefs_token=$3, prefs_token_expires_at=$4 WHERE id=$5",
                        t,
                        datetime.now(timezone.utc) + _TOKEN_TTL,
                        pt,
                        datetime.now(timezone.utc) + _PREFS_TOKEN_TTL,
                        row["id"],
                    )
                    send_token = t
                    send_prefs_token = pt
                    resend_msg = "Confirmation email resent."
            else:
                t = _make_token()
                pt = _make_token()
                await conn.execute(
                    """INSERT INTO subscribers
                       (email, source, token, token_expires_at, ip_address, user_agent,
                        prefs_token, prefs_token_expires_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                    body.email,
                    body.source,
                    t,
                    datetime.now(timezone.utc) + _TOKEN_TTL,
                    ip,
                    ua,
                    pt,
                    datetime.now(timezone.utc) + _PREFS_TOKEN_TTL,
                )
                send_token = t
                send_prefs_token = pt
                # resend_msg stays None → caller sets 201

    except asyncpg.UniqueViolationError as exc:
        constraint = exc.constraint_name or ""
        if "token" in constraint:
            # Token collision (astronomically rare) — treat as transient error
            log.error("Token uniqueness violation for %s — retry", _mask_email(body.email))
            raise HTTPException(status_code=500, detail="Subscription failed, please retry.")
        response.status_code = 200
        return MessageOut(message="Already subscribed.")
    except Exception as exc:
        log.error("subscribe error: %s", exc)
        raise HTTPException(status_code=500, detail="Subscription failed.")

    assert send_token is not None  # noqa: S101 — all non-early-return paths set send_token

    await _try_send_verification(body.email, send_token, send_prefs_token)

    if resend_msg is None:
        # status_code=201 from decorator — new subscriber created
        return MessageOut(message="Check your email to confirm.")

    response.status_code = 200  # resend / re-subscribe — idempotent, not a new resource
    return MessageOut(message=resend_msg)


@app.get("/api/confirm/{token}")
async def confirm(token: str, conn: asyncpg.Connection = Depends(get_pg_conn)):
    """
    Confirm a subscription via the emailed token.
    Always redirects — never returns JSON — so it works directly from email clients.
    """
    try:
        row = await conn.fetchrow(
            "SELECT id, status, token_expires_at FROM subscribers WHERE token = $1 LIMIT 1",
            token,
        )
        if not row:
            return RedirectResponse(url=f"{settings.site_url}/?confirmed=invalid", status_code=302)
        # Only pending rows can be confirmed; confirmed/unsubscribed both go to 'already'
        if row["status"] != "pending":
            return RedirectResponse(url=f"{settings.site_url}/?confirmed=already", status_code=302)
        if (
            row["token_expires_at"] is not None
            and row["token_expires_at"] < datetime.now(timezone.utc)
        ):
            return RedirectResponse(url=f"{settings.site_url}/?confirmed=expired", status_code=302)
        async with conn.transaction():
            updated = await conn.execute(
                "UPDATE subscribers SET status='confirmed', confirmed_at=now()"
                " WHERE id=$1 AND status='pending'"
                " AND (token_expires_at IS NULL OR token_expires_at >= now())",
                row["id"],
            )
        # If another request raced and changed status or the token just expired, treat as already/expired
        if updated == "UPDATE 0":
            return RedirectResponse(url=f"{settings.site_url}/?confirmed=already", status_code=302)
        return RedirectResponse(url=f"{settings.site_url}/?confirmed=1", status_code=302)
    except Exception as exc:
        log.error("confirm error: %s", exc)
        return RedirectResponse(url=f"{settings.site_url}/?confirmed=error", status_code=302)


@app.get("/api/unsubscribe/{token}")
async def unsubscribe_subscriber(token: str, conn: asyncpg.Connection = Depends(get_pg_conn)):
    """
    Unsubscribe via the token included in every verification email.
    Always redirects so it works directly from email clients.
    """
    try:
        row = await conn.fetchrow(
            "SELECT id, status FROM subscribers WHERE token = $1 LIMIT 1",
            token,
        )
        if not row:
            return RedirectResponse(url=f"{settings.site_url}/?unsubscribed=invalid", status_code=302)
        if row["status"] == "unsubscribed":
            return RedirectResponse(url=f"{settings.site_url}/?unsubscribed=already", status_code=302)
        async with conn.transaction():
            await conn.execute(
                "UPDATE subscribers SET status='unsubscribed', unsubscribed_at=now()"
                " WHERE id=$1 AND status != 'unsubscribed'",
                row["id"],
            )
        return RedirectResponse(url=f"{settings.site_url}/?unsubscribed=true", status_code=302)
    except Exception as exc:
        log.error("unsubscribe error: %s", exc)
        return RedirectResponse(url=f"{settings.site_url}/?unsubscribed=error", status_code=302)


@app.get("/api/preferences/{token}", include_in_schema=False)
async def preferences_page(token: str, saved: str = "", conn: asyncpg.Connection = Depends(get_pg_conn)):
    """Subscriber preferences page — frequency toggle via one-time link."""
    try:
        row = await conn.fetchrow(
            "SELECT id, email, frequency, token, prefs_token_expires_at"
            " FROM subscribers WHERE prefs_token = $1 AND status = 'confirmed' LIMIT 1",
            token,
        )
    except asyncpg.PostgresError as exc:
        log.error("preferences_page DB error: %s", exc)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    if not row:
        return _prefs_html_response("", "weekly", token, error="Link not found or already unsubscribed.")

    if (
        row["prefs_token_expires_at"] is not None
        and row["prefs_token_expires_at"] < datetime.now(timezone.utc)
    ):
        return _prefs_html_response(
            "", "weekly", token,
            error="Your preferences link has expired. Check your most recent email for a new one.",
        )

    return _prefs_html_response(row["email"], row["frequency"], token, saved=saved)


@app.post("/api/preferences/{token}", include_in_schema=False)
async def update_preferences(
    token: str,
    frequency: str = Form(...),
    conn: asyncpg.Connection = Depends(get_pg_conn),
):
    """Save subscriber frequency preference — accepts HTML form submission."""
    from pydantic import ValidationError
    try:
        body = PreferencesIn(frequency=frequency)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Invalid frequency value.")
    try:
        result = await conn.execute(
            "UPDATE subscribers SET frequency = $1 WHERE prefs_token = $2 AND status = 'confirmed'",
            body.frequency, token,
        )
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Subscriber not found.")
    except HTTPException:
        raise
    except Exception as exc:
        log.error("update_preferences error: %s", exc)
        raise HTTPException(status_code=500, detail="Could not save preferences.")

    return RedirectResponse(url=f"{settings.site_url}/api/preferences/{token}?saved=1", status_code=303)


@app.post("/api/contact", response_model=MessageOut, status_code=200)
@limiter.limit("5/minute")
async def contact(request: Request, body: ContactIn):
    """
    Handle consulting enquiries from the work-with-me page.
    Validates the request, optionally verifies Turnstile, and forwards
    the enquiry as an email to admin@cloudista.org via SES.
    """
    ip = _real_ip(request)

    if body.cf_turnstile_token:
        if not settings.turnstile_secret:
            log.warning("Turnstile token received but TURNSTILE_SECRET not configured — skipping")
        else:
            result = await _verify_turnstile(body.cf_turnstile_token, ip)
            if result is TurnstileResult.INVALID:
                raise HTTPException(status_code=400, detail="CAPTCHA verification failed.")

    engagement_labels = {
        "audit": "Platform audit",
        "sprint": "Sprint embed",
        "retainer": "Advisory retainer",
        "other": "Something else",
    }
    engagement_label = engagement_labels.get(body.engagement, "Not specified")

    subject, html_body, text_body = build_contact_email(
        name=body.name,
        email=body.email,
        company=body.company,
        engagement_label=engagement_label,
        situation=body.situation,
    )

    try:
        await asyncio.to_thread(
            _ses.send_email,
            Source=settings.from_email,
            Destination={"ToAddresses": ["admin@cloudista.org"]},
            ReplyToAddresses=[body.email],
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                },
            },
        )
        log.info("Contact enquiry from %s (%s)", body.name, body.email)
    except (BotoCoreError, ClientError) as exc:
        log.error("SES send failed for contact enquiry from %s: %s", body.email, exc)
        raise HTTPException(status_code=503, detail="Failed to send message. Please try again.")

    return MessageOut(message="Message sent. I'll be in touch within one business day.")


@app.post("/api/ses-webhook", include_in_schema=False)
async def ses_webhook(request: Request, conn: asyncpg.Connection = Depends(get_pg_conn)):
    """
    Handle SES bounce and complaint notifications forwarded via SNS.

    Setup: configure an SES notification rule that publishes to an SNS topic,
    then subscribe this endpoint as an HTTPS subscriber to that topic.
    All incoming messages are signature-verified against the AWS-published cert.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON.")

    # Verify signature once before branching on message type.
    if not _verify_sns_signature(body):
        log.warning("SNS message failed signature check — rejected (type=%s)", body.get("Type"))
        raise HTTPException(status_code=400, detail="Invalid SNS signature.")

    msg_type = body.get("Type", "")

    # SNS first sends a SubscriptionConfirmation — auto-confirm after signature is validated.
    if msg_type == "SubscriptionConfirmation":
        subscribe_url = body.get("SubscribeURL", "")
        parsed = urllib.parse.urlparse(subscribe_url)
        # Only follow confirmation URLs from sns.amazonaws.com (prevents SSRF)
        if parsed.scheme == "https" and re.fullmatch(
            r"sns\.[a-z0-9-]+\.amazonaws\.com", parsed.hostname or ""
        ):
            try:
                await asyncio.to_thread(urllib.request.urlopen, subscribe_url, None, 5)
                log.info("SNS subscription confirmed for topic: %s", body.get("TopicArn"))
            except Exception as exc:
                log.warning("SNS subscription confirmation failed: %s", exc)
        else:
            log.warning("SNS SubscribeURL hostname rejected: %s", parsed.hostname)
        return JSONResponse(content={"status": "confirmed"})

    if msg_type != "Notification":
        return JSONResponse(content={"status": "ignored"})

    # Validate TopicArn if configured (prevents processing from unexpected topics)
    if settings.ses_topic_arn and body.get("TopicArn") != settings.ses_topic_arn:
        log.warning("SNS TopicArn mismatch: %s", body.get("TopicArn"))
        raise HTTPException(status_code=400, detail="Unexpected SNS topic.")

    try:
        notification = json.loads(body.get("Message", "{}"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid SNS message payload.")

    notification_type = notification.get("notificationType")
    emails: list[str] = []

    if notification_type == "Bounce":
        if notification.get("bounce", {}).get("bounceType") == "Permanent":
            emails = [
                r["emailAddress"]
                for r in notification.get("bounce", {}).get("bouncedRecipients", [])
            ]
            log.info("Permanent bounce for %d address(es)", len(emails))
    elif notification_type == "Complaint":
        emails = [
            r["emailAddress"]
            for r in notification.get("complaint", {}).get("complainedRecipients", [])
        ]
        log.info("Complaint received for %d address(es)", len(emails))

    if emails:
        async with conn.transaction():
            await conn.execute(
                "UPDATE subscribers SET status='unsubscribed', unsubscribed_at=now()"
                " WHERE email = ANY($1::text[]) AND status != 'unsubscribed'",
                emails,
            )
        log.info("Marked unsubscribed (%s): %s", notification_type, emails)

    return JSONResponse(content={"status": "ok"})
