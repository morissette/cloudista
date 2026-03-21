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
import hashlib
import json
import logging
import urllib.parse
import urllib.request
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum

import asyncpg
import boto3
from blog_routes import html_router as blog_html_router
from blog_routes import router as blog_router
from botocore.exceptions import BotoCoreError, ClientError
from config import settings
from dependencies import close_pool, get_pg_conn, init_pool
from email_template import build_verification_email
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from schemas import HealthOut, MessageOut, SubscribeIn
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_TOKEN_TTL = timedelta(hours=72)


# ---------------------------------------------------------------------------
# Turnstile result enum
# ---------------------------------------------------------------------------
class TurnstileResult(Enum):
    VALID = "valid"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Rate limiter (keyed by real client IP)
# ---------------------------------------------------------------------------
def _real_ip(request: Request) -> str:
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


limiter = Limiter(key_func=_real_ip)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
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
        "https://cloudista.org",
        "https://www.cloudista.org",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    max_age=3600,
)

# boto3 picks up credentials from the EC2 instance's IAM role automatically.
_ses = boto3.client("ses", region_name=settings.aws_region)


# ---------------------------------------------------------------------------
# Request-ID middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = req_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token(email: str) -> str:
    raw = f"{email}{uuid.uuid4()}{datetime.now(timezone.utc).timestamp()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _verify_turnstile_sync(token: str, ip: str) -> TurnstileResult:
    payload = urllib.parse.urlencode({
        "secret": settings.turnstile_secret,
        "response": token,
        "remoteip": ip,
    }).encode()
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


def _send_verification(email: str, token: str) -> None:
    """
    Send a verification email via AWS SES.
    Raises on failure so the caller can decide whether to propagate.
    """
    confirm_url = f"{settings.confirm_base_url}/{token}"
    unsubscribe_url = f"{settings.site_url}/api/unsubscribe/{token}"
    subject, html, text = build_verification_email(confirm_url, unsubscribe_url)

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
    log.info("Verification email sent → %s", email)


async def _try_send_verification(email: str, token: str) -> None:
    """Send verification email; log but don't raise on SES failure."""
    try:
        await asyncio.to_thread(_send_verification, email, token)
    except (BotoCoreError, ClientError) as exc:
        log.error("SES send failed for %s: %s", email, exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthOut)
async def health():
    """Liveness probe. Always returns 200; DB connectivity reported in body."""
    from dependencies import _pg_pool  # noqa: PLC0415 — intentional late import to avoid circular

    db_ok = True
    db_error = None
    if _pg_pool is None:
        db_ok = False
        db_error = "Pool not initialised"
    else:
        try:
            async with _pg_pool.acquire(timeout=2.0) as conn:
                await conn.fetchval("SELECT 1")
        except Exception as exc:
            log.warning("DB ping failed: %s", exc)
            db_ok = False
            db_error = "Connection failed"  # don't leak internal details
    return HealthOut(
        status="ok",
        db="ok" if db_ok else "unavailable",
        db_error=db_error,
    )


@app.post("/api/subscribe", response_model=MessageOut)
@limiter.limit("5/minute")
async def subscribe(
    request: Request,
    body: SubscribeIn,
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

    new_token: str | None = None
    resend_token: str | None = None
    resend_msg: str = ""

    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, status, token, token_expires_at FROM subscribers WHERE email = $1 LIMIT 1",
                body.email,
            )

            if row:
                if row["status"] == "confirmed":
                    return JSONResponse(status_code=200, content={"message": "Already confirmed."})

                if row["status"] == "unsubscribed":
                    t = _make_token(body.email)
                    await conn.execute(
                        "UPDATE subscribers SET status='pending', token=$1, token_expires_at=$2 WHERE id=$3",
                        t,
                        datetime.now(timezone.utc) + _TOKEN_TTL,
                        row["id"],
                    )
                    resend_token = t
                    resend_msg = "Re-subscribed — check your email."
                else:
                    # pending — always rotate token on resend so old links are invalidated
                    t = _make_token(body.email)
                    await conn.execute(
                        "UPDATE subscribers SET token=$1, token_expires_at=$2 WHERE id=$3",
                        t,
                        datetime.now(timezone.utc) + _TOKEN_TTL,
                        row["id"],
                    )
                    resend_token = t
                    resend_msg = "Confirmation email resent."
            else:
                t = _make_token(body.email)
                await conn.execute(
                    """INSERT INTO subscribers (email, source, token, token_expires_at, ip_address, user_agent)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    body.email,
                    body.source,
                    t,
                    datetime.now(timezone.utc) + _TOKEN_TTL,
                    ip,
                    ua,
                )
                new_token = t

    except asyncpg.UniqueViolationError as exc:
        constraint = exc.constraint_name or ""
        if "token" in constraint:
            # Token collision (astronomically rare) — treat as transient error
            log.error("Token uniqueness violation for %s — retry", body.email)
            raise HTTPException(status_code=500, detail="Subscription failed, please retry.")
        return JSONResponse(status_code=200, content={"message": "Already subscribed."})
    except Exception as exc:
        log.error("subscribe error: %s", exc)
        raise HTTPException(status_code=500, detail="Subscription failed.")

    if new_token:
        await _try_send_verification(body.email, new_token)
        return JSONResponse(status_code=201, content={"message": "Check your email to confirm."})

    await _try_send_verification(body.email, resend_token)  # type: ignore[arg-type]
    return JSONResponse(status_code=200, content={"message": resend_msg})


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
        if row["status"] == "confirmed":
            return RedirectResponse(url=f"{settings.site_url}/?confirmed=already", status_code=302)
        if (
            row["token_expires_at"] is not None
            and row["token_expires_at"] < datetime.now(timezone.utc)
        ):
            return RedirectResponse(url=f"{settings.site_url}/?confirmed=expired", status_code=302)
        async with conn.transaction():
            await conn.execute(
                "UPDATE subscribers SET status='confirmed', confirmed_at=now() WHERE id=$1",
                row["id"],
            )
        return RedirectResponse(url=f"{settings.site_url}/?confirmed=true", status_code=302)
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
                "UPDATE subscribers SET status='unsubscribed', unsubscribed_at=now() WHERE id=$1",
                row["id"],
            )
        return RedirectResponse(url=f"{settings.site_url}/?unsubscribed=true", status_code=302)
    except Exception as exc:
        log.error("unsubscribe error: %s", exc)
        return RedirectResponse(url=f"{settings.site_url}/?unsubscribed=error", status_code=302)


@app.post("/api/ses-webhook", include_in_schema=False)
async def ses_webhook(request: Request, conn: asyncpg.Connection = Depends(get_pg_conn)):
    """
    Handle SES bounce and complaint notifications forwarded via SNS.

    Setup: configure an SES notification rule that publishes to an SNS topic,
    then subscribe this endpoint as an HTTPS subscriber to that topic.

    NOTE: SNS message signature verification is not yet implemented.
    Until it is, restrict access to this endpoint at the nginx/firewall level
    to SNS IP ranges (published at https://ip-ranges.amazonaws.com/ip-ranges.json).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON.")

    msg_type = body.get("Type", "")

    # SNS first sends a SubscriptionConfirmation — auto-confirm from amazonaws.com URLs only.
    if msg_type == "SubscriptionConfirmation":
        subscribe_url = body.get("SubscribeURL", "")
        if subscribe_url.startswith("https://sns.amazonaws.com/"):
            try:
                await asyncio.to_thread(urllib.request.urlopen, subscribe_url, None, 5)
                log.info("SNS subscription confirmed for topic: %s", body.get("TopicArn"))
            except Exception as exc:
                log.warning("SNS subscription confirmation failed: %s", exc)
        return JSONResponse(content={"status": "confirmed"})

    if msg_type != "Notification":
        return JSONResponse(content={"status": "ignored"})

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
            for email in emails:
                await conn.execute(
                    "UPDATE subscribers SET status='unsubscribed', unsubscribed_at=now()"
                    " WHERE email=$1 AND status != 'unsubscribed'",
                    email,
                )
        log.info("Marked unsubscribed (%s): %s", notification_type, emails)

    return JSONResponse(content={"status": "ok"})
