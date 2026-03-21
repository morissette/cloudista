"""
Cloudista API
-------------
POST /api/subscribe        – register an email; sends a verification email via SES
GET  /api/confirm/{token}  – confirm subscription; redirects to site with status param
GET  /api/health           – liveness probe (validates DB connectivity)
"""

import hashlib
import json as _json
import logging
import os
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

import boto3
import pymysql
import pymysql.cursors
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr

from email_template import build_verification_email
from blog_routes import html_router as blog_html_router
from blog_routes import router as blog_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
_DB_CONFIG: dict = {
    "host":            os.environ["DB_HOST"],
    "port":            int(os.environ.get("DB_PORT", 3306)),
    "user":            os.environ["DB_USER"],
    "password":        os.environ["DB_PASSWORD"],
    "database":        os.environ["DB_NAME"],
    "charset":         "utf8mb4",
    "cursorclass":     pymysql.cursors.DictCursor,
    "connect_timeout": 5,
}

AWS_REGION        = os.environ.get("AWS_REGION",        "us-east-1")
FROM_EMAIL        = os.environ.get("FROM_EMAIL",        "noreply@cloudista.org")
CONFIRM_BASE_URL  = os.environ.get("CONFIRM_BASE_URL",  "https://cloudista.org/api/confirm")
SITE_URL          = os.environ.get("SITE_URL",          "https://cloudista.org")
TURNSTILE_SECRET  = os.environ.get("TURNSTILE_SECRET",  "")

# boto3 picks up credentials from the EC2 instance's IAM role automatically.
_ses = boto3.client("ses", region_name=AWS_REGION)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Cloudista API", docs_url=None, redoc_url=None)

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

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SubscribeIn(BaseModel):
    email: EmailStr
    source: str = "coming_soon"
    cf_turnstile_token: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connect() -> pymysql.connections.Connection:
    return pymysql.connect(**_DB_CONFIG)


def _make_token(email: str) -> str:
    raw = f"{email}{uuid.uuid4()}{datetime.utcnow().timestamp()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _real_ip(request: Request) -> str | None:
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else None)
    )


def _verify_turnstile(token: str, remote_ip: str | None) -> bool:
    """Verify a Cloudflare Turnstile token. Returns True if valid."""
    params: dict = {"secret": TURNSTILE_SECRET, "response": token}
    if remote_ip:
        params["remoteip"] = remote_ip
    data = urllib.parse.urlencode(params).encode()
    try:
        req = urllib.request.Request(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=data,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = _json.loads(resp.read())
        return bool(result.get("success"))
    except Exception as exc:
        log.error("Turnstile verify error: %s", exc)
        return False


def _send_verification(email: str, token: str) -> None:
    """
    Send a verification email via AWS SES.
    Raises on failure so the caller can decide whether to propagate.
    """
    confirm_url = f"{CONFIRM_BASE_URL}/{token}"
    subject, html, text = build_verification_email(confirm_url)

    _ses.send_email(
        Source=FROM_EMAIL,
        Destination={"ToAddresses": [email]},
        Message={
            "Subject": {"Data": subject,  "Charset": "UTF-8"},
            "Body": {
                "Html": {"Data": html, "Charset": "UTF-8"},
                "Text": {"Data": text, "Charset": "UTF-8"},
            },
        },
    )
    log.info("Verification email sent → %s", email)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    """Liveness probe. Always returns 200; DB connectivity reported in body."""
    db_ok = True
    db_error = None
    try:
        conn = _connect()
        conn.ping()
        conn.close()
    except Exception as exc:
        log.warning("DB ping failed: %s", exc)
        db_ok = False
        db_error = str(exc)
    return {"status": "ok", "db": "ok" if db_ok else "unavailable", **({"db_error": db_error} if db_error else {})}


@app.post("/api/subscribe", status_code=201)
def subscribe(body: SubscribeIn, request: Request):
    """
    Register an email address for launch notifications.

    Flow:
    1. Insert row with status='pending'
    2. Send verification email via SES
    3. User clicks link → GET /api/confirm/{token}
    """
    ip    = _real_ip(request)
    ua    = request.headers.get("User-Agent", "")[:500]
    token = _make_token(body.email)

    # Verify CAPTCHA token when the client flagged suspicious behaviour
    if body.cf_turnstile_token:
        if not TURNSTILE_SECRET:
            log.warning("TURNSTILE_SECRET not configured; skipping verification")
        elif not _verify_turnstile(body.cf_turnstile_token, ip):
            raise HTTPException(status_code=400, detail="CAPTCHA verification failed. Please try again.")

    try:
        conn = _connect()
    except Exception as exc:
        log.error("DB connect failed: %s", exc)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status FROM subscribers WHERE email = %s LIMIT 1",
                (body.email,),
            )
            row = cur.fetchone()

            if row:
                if row["status"] == "unsubscribed":
                    # Re-subscribe: reset to pending and resend verification
                    cur.execute(
                        """UPDATE subscribers
                              SET status          = 'pending',
                                  token           = %s,
                                  unsubscribed_at = NULL
                            WHERE id = %s""",
                        (token, row["id"]),
                    )
                    conn.commit()
                    _try_send_verification(body.email, token)
                    return {"message": "Welcome back! Check your email to confirm."}

                if row["status"] == "pending":
                    # Resend verification in case they missed the first one
                    _try_send_verification(body.email, row["token"])
                    return {"message": "Check your email — we've resent the confirmation link."}

                # already confirmed
                return {"message": "You're already confirmed — we'll notify you at launch!"}

            cur.execute(
                """INSERT INTO subscribers
                          (email, source, token, ip_address, user_agent)
                   VALUES (%s,    %s,     %s,    %s,         %s)""",
                (body.email, body.source, token, ip, ua),
            )
            conn.commit()

        # Send outside the cursor context (network call)
        _try_send_verification(body.email, token)
        log.info("New subscriber: %s via %s", body.email, body.source)
        return {"message": "Almost there — check your email to confirm your subscription."}

    except pymysql.err.IntegrityError:
        return {"message": "Check your email — we've sent you a confirmation link."}
    except Exception as exc:
        conn.rollback()
        log.error("subscribe(%s) error: %s", body.email, exc)
        raise HTTPException(status_code=500, detail="Failed to save your subscription.")
    finally:
        conn.close()


def _try_send_verification(email: str, token: str) -> None:
    """Send verification email; log but don't raise on SES failure."""
    try:
        _send_verification(email, token)
    except (BotoCoreError, ClientError) as exc:
        log.error("SES send failed for %s: %s", email, exc)


@app.get("/api/confirm/{token}")
def confirm(token: str):
    """
    Confirm a subscription via the emailed token.
    Always redirects — never returns JSON — so it works directly from email clients.
    """
    try:
        conn = _connect()
    except Exception as exc:
        log.error("DB connect failed during confirm: %s", exc)
        return RedirectResponse(url=f"{SITE_URL}?confirmed=error", status_code=302)

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status FROM subscribers WHERE token = %s LIMIT 1",
                (token,),
            )
            row = cur.fetchone()

            if not row:
                log.warning("confirm: unknown token %s…", token[:12])
                return RedirectResponse(url=f"{SITE_URL}?confirmed=invalid", status_code=302)

            if row["status"] == "confirmed":
                return RedirectResponse(url=f"{SITE_URL}?confirmed=already", status_code=302)

            cur.execute(
                "UPDATE subscribers SET status='confirmed', confirmed_at=NOW() WHERE id=%s",
                (row["id"],),
            )
            conn.commit()
            log.info("Confirmed subscriber id=%s", row["id"])
            return RedirectResponse(url=f"{SITE_URL}?confirmed=1", status_code=302)

    except Exception as exc:
        conn.rollback()
        log.error("confirm error for token %s…: %s", token[:12], exc)
        return RedirectResponse(url=f"{SITE_URL}?confirmed=error", status_code=302)
    finally:
        conn.close()
