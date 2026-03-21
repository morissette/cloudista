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
import hashlib
import json
import logging
import re
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
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate
from dependencies import _real_ip, close_pool, get_pg_conn, init_pool, limiter
from email_template import build_verification_email
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from schemas import HealthOut, MessageOut, SubscribeIn
from slowapi import _rate_limit_exceeded_handler
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

# Simple in-process SNS cert cache (keyed by URL; certs are long-lived)
_SNS_CERT_CACHE: dict[str, bytes] = {}

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
    raw = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    # Strip control characters to prevent CRLF header injection
    req_id = re.sub(r"[^\x20-\x7E]", "", raw)[:64] or str(uuid.uuid4())
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

    cert_pem = _SNS_CERT_CACHE.get(cert_url)
    if cert_pem is None:
        try:
            with urllib.request.urlopen(cert_url, timeout=5) as resp:
                cert_pem = resp.read()
            _SNS_CERT_CACHE[cert_url] = cert_pem
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


@app.post("/api/subscribe", response_model=MessageOut, status_code=200)
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
    resend_msg: str | None = None  # None signals new insert (→ 201)

    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, status, token, token_expires_at FROM subscribers WHERE email = $1 LIMIT 1",
                body.email,
            )

            if row:
                if row["status"] == "confirmed":
                    return MessageOut(message="Already confirmed.")

                if row["status"] == "unsubscribed":
                    t = _make_token(body.email)
                    await conn.execute(
                        "UPDATE subscribers SET status='pending', token=$1, token_expires_at=$2 WHERE id=$3",
                        t,
                        datetime.now(timezone.utc) + _TOKEN_TTL,
                        row["id"],
                    )
                    send_token = t
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
                    send_token = t
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
                send_token = t
                # resend_msg stays None → caller sets 201

    except asyncpg.UniqueViolationError as exc:
        constraint = exc.constraint_name or ""
        if "token" in constraint:
            # Token collision (astronomically rare) — treat as transient error
            log.error("Token uniqueness violation for %s — retry", body.email)
            raise HTTPException(status_code=500, detail="Subscription failed, please retry.")
        return MessageOut(message="Already subscribed.")
    except Exception as exc:
        log.error("subscribe error: %s", exc)
        raise HTTPException(status_code=500, detail="Subscription failed.")

    assert send_token is not None  # noqa: S101 — all non-early-return paths set send_token

    await _try_send_verification(body.email, send_token)

    if resend_msg is None:
        response.status_code = 201
        return MessageOut(message="Check your email to confirm.")

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
    All incoming messages are signature-verified against the AWS-published cert.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON.")

    msg_type = body.get("Type", "")

    # SNS first sends a SubscriptionConfirmation — auto-confirm only after verifying signature.
    if msg_type == "SubscriptionConfirmation":
        if not _verify_sns_signature(body):
            log.warning("SNS SubscriptionConfirmation failed signature check — rejected")
            raise HTTPException(status_code=400, detail="Invalid SNS signature.")
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

    # Verify signature before processing notifications
    if not _verify_sns_signature(body):
        log.warning("SNS Notification failed signature check — rejected")
        raise HTTPException(status_code=400, detail="Invalid SNS signature.")

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
            for email in emails:
                await conn.execute(
                    "UPDATE subscribers SET status='unsubscribed', unsubscribed_at=now()"
                    " WHERE email=$1 AND status != 'unsubscribed'",
                    email,
                )
        log.info("Marked unsubscribed (%s): %s", notification_type, emails)

    return JSONResponse(content={"status": "ok"})
