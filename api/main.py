"""
Cloudista API
-------------
POST /api/subscribe        – register an email; sends a verification email via SES
GET  /api/confirm/{token}  – confirm subscription; redirects to site with status param
GET  /api/health           – liveness probe (validates DB connectivity)
"""

import hashlib
import json
import logging
import urllib.parse
import urllib.request
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum

import boto3
import psycopg2
import psycopg2.errors
from blog_routes import html_router as blog_html_router
from blog_routes import router as blog_router
from botocore.exceptions import BotoCoreError, ClientError
from config import settings
from dependencies import close_pool, get_pg_conn, init_pool
from email_template import build_verification_email
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from psycopg2.extensions import connection as PgConn
from schemas import HealthOut, MessageOut, SubscribeIn

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


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
    init_pool()
    yield
    close_pool()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Cloudista API", docs_url=None, redoc_url=None, lifespan=lifespan)

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
# Helpers
# ---------------------------------------------------------------------------

def _make_token(email: str) -> str:
    raw = f"{email}{uuid.uuid4()}{datetime.now(timezone.utc).timestamp()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _real_ip(request: Request) -> str | None:
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else None)
    )


def _verify_turnstile(token: str, ip: str | None) -> TurnstileResult:
    """Verify a Cloudflare Turnstile token. Returns TurnstileResult enum."""
    payload = urllib.parse.urlencode({
        "secret": settings.turnstile_secret,
        "response": token,
        **({"remoteip": ip} if ip else {}),
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


def _send_verification(email: str, token: str) -> None:
    """
    Send a verification email via AWS SES.
    Raises on failure so the caller can decide whether to propagate.
    """
    confirm_url = f"{settings.confirm_base_url}/{token}"
    subject, html, text = build_verification_email(confirm_url)

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


def _try_send_verification(email: str, token: str) -> None:
    """Send verification email; log but don't raise on SES failure."""
    try:
        _send_verification(email, token)
    except (BotoCoreError, ClientError) as exc:
        log.error("SES send failed for %s: %s", email, exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthOut)
def health():
    """Liveness probe. Always returns 200; DB connectivity reported in body."""
    from dependencies import _pg_pool  # noqa: PLC0415 — intentional late import to avoid circular

    db_ok = True
    db_error = None
    if _pg_pool is None:
        db_ok = False
        db_error = "Pool not initialised"
    else:
        conn = None
        try:
            conn = _pg_pool.getconn()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        except Exception as exc:
            log.warning("DB ping failed: %s", exc)
            db_ok = False
            db_error = str(exc)
        finally:
            if conn is not None:
                _pg_pool.putconn(conn)
    return HealthOut(
        status="ok",
        db="ok" if db_ok else "unavailable",
        db_error=db_error,
    )


@app.post("/api/subscribe", response_model=MessageOut)
def subscribe(body: SubscribeIn, request: Request, conn: PgConn = Depends(get_pg_conn)):
    """
    Register an email address for launch notifications.

    Flow:
    1. Insert row with status='pending'
    2. Send verification email via SES
    3. User clicks link → GET /api/confirm/{token}
    """
    ip = _real_ip(request)
    ua = request.headers.get("User-Agent", "")[:500]
    token = _make_token(body.email)

    if body.cf_turnstile_token:
        if not settings.turnstile_secret:
            log.warning("Turnstile token received but TURNSTILE_SECRET not configured — skipping")
        else:
            result = _verify_turnstile(body.cf_turnstile_token, ip)
            if result is TurnstileResult.INVALID:
                raise HTTPException(status_code=400, detail="CAPTCHA verification failed.")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status, token FROM subscribers WHERE email = %s LIMIT 1",
                (body.email,),
            )
            row = cur.fetchone()

            if row:
                if row["status"] == "confirmed":
                    return JSONResponse(status_code=200, content={"message": "Already confirmed."})
                if row["status"] == "unsubscribed":
                    cur.execute(
                        "UPDATE subscribers SET status='pending', token=%s WHERE id=%s",
                        (token, row["id"]),
                    )
                    conn.commit()
                    _try_send_verification(body.email, token)
                    return JSONResponse(
                        status_code=200,
                        content={"message": "Re-subscribed — check your email."},
                    )
                # pending — resend
                _try_send_verification(body.email, row["token"])
                return JSONResponse(
                    status_code=200,
                    content={"message": "Confirmation email resent."},
                )

            cur.execute(
                """INSERT INTO subscribers (email, source, token, ip_address, user_agent)
                   VALUES (%s, %s, %s, %s, %s)""",
                (body.email, body.source, token, ip, ua),
            )
            conn.commit()
        _try_send_verification(body.email, token)
        return JSONResponse(
            status_code=201,
            content={"message": "Check your email to confirm."},
        )

    except psycopg2.errors.UniqueViolation as exc:
        conn.rollback()
        constraint = getattr(getattr(exc, "diag", None), "constraint_name", None)
        if constraint and "token" in constraint:
            # Token collision (astronomically rare) — treat as transient error
            log.error("Token uniqueness violation for %s — retry", body.email)
            raise HTTPException(status_code=500, detail="Subscription failed, please retry.")
        return JSONResponse(status_code=200, content={"message": "Already subscribed."})
    except Exception as exc:
        conn.rollback()
        log.error("subscribe error: %s", exc)
        raise HTTPException(status_code=500, detail="Subscription failed.")


@app.get("/api/confirm/{token}")
def confirm(token: str, conn: PgConn = Depends(get_pg_conn)):
    """
    Confirm a subscription via the emailed token.
    Always redirects — never returns JSON — so it works directly from email clients.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status FROM subscribers WHERE token = %s LIMIT 1",
                (token,),
            )
            row = cur.fetchone()
            if not row:
                return RedirectResponse(url=f"{settings.site_url}/?confirmed=invalid", status_code=302)
            if row["status"] == "confirmed":
                return RedirectResponse(url=f"{settings.site_url}/?confirmed=already", status_code=302)
            cur.execute(
                "UPDATE subscribers SET status='confirmed', confirmed_at=now() WHERE id=%s",
                (row["id"],),
            )
            conn.commit()
        return RedirectResponse(url=f"{settings.site_url}/?confirmed=true", status_code=302)
    except Exception as exc:
        conn.rollback()
        log.error("confirm error: %s", exc)
        return RedirectResponse(url=f"{settings.site_url}/?confirmed=error", status_code=302)
