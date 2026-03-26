"""
HTML + plain-text templates for Cloudista emails.

Usage:
    subject, html, text = build_verification_email(
        "https://cloudista.org/api/confirm/abc123",
        "https://cloudista.org/api/unsubscribe/abc123",
        "https://cloudista.org/api/preferences/abc123",
    )
"""
from __future__ import annotations  # enables tuple[...] hints on Python 3.8

import html as _html

from config import settings

_SITE_URL = settings.site_url


# ── Shared layout helpers ──────────────────────────────────────────────────────

def _email_html_wrapper(header_extra: str, body_html: str, footer_html: str) -> str:
    """Wrap content in the standard Cloudista email shell."""
    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <!--[if mso]>
  <noscript>
    <xml><o:OfficeDocumentSettings>
      <o:PixelsPerInch>96</o:PixelsPerInch>
    </o:OfficeDocumentSettings></xml>
  </noscript>
  <![endif]-->
  <style>
    @media only screen and (max-width: 600px) {{
      .email-container {{ width: 100% !important; }}
      .content-pad     {{ padding: 28px 24px !important; }}
      .footer-pad      {{ padding: 18px 24px !important; }}
      .cta-btn a       {{ padding: 13px 22px !important; font-size: 15px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;
             font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;
             -webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">

  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:#f1f5f9;min-height:100vh;">
    <tr>
      <td align="center" valign="top" style="padding:48px 16px 48px;">

        <table class="email-container" cellpadding="0" cellspacing="0" border="0"
               style="width:100%;max-width:560px;">

          <!-- ── HEADER ────────────────────────────────────────────── -->
          <tr>
            <td style="border-radius:14px 14px 0 0;
                       background:linear-gradient(135deg,#2563eb 0%,#4f46e5 50%,#7c3aed 100%);
                       padding:36px 40px 32px;text-align:center;">

              <table cellpadding="0" cellspacing="0" border="0" align="center">
                <tr>
                  <td style="background:rgba(255,255,255,.18);border-radius:9px;
                              padding:7px 9px 5px;vertical-align:middle;">
                    <span style="font-size:17px;line-height:1;display:block;">&#9729;</span>
                  </td>
                  <td style="padding-left:9px;vertical-align:middle;">
                    <span style="color:#ffffff;font-size:20px;font-weight:800;
                                 letter-spacing:-0.03em;">Cloudista</span>
                  </td>
                </tr>
              </table>

              <p style="margin:16px 0 0;color:rgba(255,255,255,.7);
                         font-size:13px;font-weight:500;letter-spacing:0.02em;">
                All Things Cloud
              </p>
              {header_extra}
            </td>
          </tr>

          <!-- ── BODY ──────────────────────────────────────────────── -->
          <tr>
            <td class="content-pad"
                style="background:#ffffff;padding:40px 40px 36px;
                       border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">
              {body_html}
            </td>
          </tr>

          {footer_html}

        </table>

      </td>
    </tr>
  </table>

</body>
</html>"""


def _email_footer_html(unsubscribe_url: str, prefs_url: str) -> str:
    """Shared footer HTML for digest and immediate notification emails."""
    _unsub = _html.escape(unsubscribe_url, quote=True)
    prefs_link = (
        (
            f' &nbsp;&middot;&nbsp; <a href="{_html.escape(prefs_url, quote=True)}"'
            ' style="color:#64748b;text-decoration:none;">Manage preferences</a>'
        )
        if prefs_url else ""
    )
    return f"""          <!-- ── FOOTER ─────────────────────────────────────────────── -->
          <tr>
            <td class="footer-pad"
                style="background:#f8fafc;
                       border:1px solid #e2e8f0;border-top:none;
                       border-radius:0 0 14px 14px;
                       padding:20px 40px;text-align:center;">

              <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;line-height:1.65;">
                <a href="{_unsub}"
                   style="color:#64748b;text-decoration:none;">Unsubscribe</a>{prefs_link}
              </p>
              <p style="margin:0;font-size:12px;color:#cbd5e1;">
                &copy; 2026 Cloudista &nbsp;&middot;&nbsp; All rights reserved
              </p>

            </td>
          </tr>"""


def _email_verification_footer_html(unsubscribe_url: str, prefs_url: str) -> str:
    """Footer HTML for the verification email (includes signup attribution text)."""
    _unsub = _html.escape(unsubscribe_url, quote=True)
    _site = _html.escape(_SITE_URL, quote=True)
    _prefs_part = (
        f' &nbsp;&middot;&nbsp; <a href="{_html.escape(prefs_url, quote=True)}"'
        f' style="color:#64748b;text-decoration:none;">Manage preferences</a>'
    ) if prefs_url else ""
    return f"""          <!-- ── FOOTER ─────────────────────────────────────────────── -->
          <tr>
            <td class="footer-pad"
                style="background:#f8fafc;
                       border:1px solid #e2e8f0;border-top:none;
                       border-radius:0 0 14px 14px;
                       padding:20px 40px;text-align:center;">

              <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;line-height:1.65;">
                You received this email because someone signed up at
                <a href="{_site}"
                   style="color:#64748b;text-decoration:none;">cloudista.org</a>.
                If that wasn't you, you can safely ignore this email or
                <a href="{_unsub}"
                   style="color:#64748b;text-decoration:none;">unsubscribe</a>{_prefs_part}.
              </p>
              <p style="margin:0;font-size:12px;color:#cbd5e1;">
                &copy; 2026 Cloudista &nbsp;&middot;&nbsp; All rights reserved
              </p>

            </td>
          </tr>"""


def _email_footer_text(unsubscribe_url: str, prefs_url: str) -> str:
    """Shared footer plain text for digest and immediate notification emails."""
    lines = [
        "---",
        f"Unsubscribe: {unsubscribe_url}",
    ]
    if prefs_url:
        lines.append(f"Manage preferences: {prefs_url}")
    lines.append("\n© 2026 Cloudista")
    return "\n".join(lines)


# ── Public builders ────────────────────────────────────────────────────────────

def build_verification_email(confirm_url: str, unsubscribe_url: str, prefs_url: str = "") -> tuple[str, str, str]:
    """Return (subject, html_body, text_body)."""
    subject = "Confirm your Cloudista subscription"
    _confirm = _html.escape(confirm_url, quote=True)

    body_html = f"""
              <!-- Heading -->
              <h1 style="margin:0 0 14px;font-size:26px;font-weight:900;
                          color:#0f172a;letter-spacing:-0.035em;line-height:1.15;">
                One click to confirm
              </h1>

              <!-- Body copy -->
              <p style="margin:0 0 14px;font-size:15.5px;color:#475569;line-height:1.75;">
                Thanks for subscribing — you're one click away from getting new posts
                delivered straight to your inbox.
              </p>
              <p style="margin:0 0 32px;font-size:15.5px;color:#475569;line-height:1.75;">
                Cloudista covers cloud infrastructure, DevOps, and platform engineering
                from the field — AWS, Azure, GCP, Kubernetes, and everything in between.
              </p>

              <!-- ── CTA button ── -->
              <!--[if mso]>
              <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml"
                           xmlns:w="urn:schemas-microsoft-com:office:word"
                           href="{_confirm}"
                           style="height:50px;v-text-anchor:middle;width:220px;"
                           arcsize="16%" strokecolor="#1d4ed8" fillcolor="#2563eb">
                <w:anchorlock/>
                <center style="color:#ffffff;font-family:sans-serif;
                               font-size:16px;font-weight:700;">
                  Confirm my email &rarr;
                </center>
              </v:roundrect>
              <![endif]-->
              <!--[if !mso]><!-->
              <table class="cta-btn" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="border-radius:9px;background:#2563eb;
                              box-shadow:0 4px 14px rgba(37,99,235,.35);">
                    <a href="{_confirm}" target="_blank"
                       style="display:inline-block;padding:15px 30px;
                              color:#ffffff;font-size:16px;font-weight:700;
                              text-decoration:none;letter-spacing:-0.01em;
                              border-radius:9px;line-height:1;">
                      Confirm my email &nbsp;&rarr;
                    </a>
                  </td>
                </tr>
              </table>
              <!--<![endif]-->

              <!-- Expiry note -->
              <p style="margin:22px 0 28px;font-size:13px;color:#94a3b8;line-height:1.6;">
                This link is unique to you and expires in <strong>72 hours</strong>.
              </p>

              <!-- Fallback URL -->
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="border-top:1px solid #f1f5f9;padding-top:24px;">
                    <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;">
                      Button not working? Copy and paste this URL into your browser:
                    </p>
                    <p style="margin:0;font-size:11.5px;word-break:break-all;line-height:1.6;">
                      <a href="{_confirm}"
                         style="color:#2563eb;text-decoration:none;">{_confirm}</a>
                    </p>
                  </td>
                </tr>
              </table>"""

    footer_html = _email_verification_footer_html(unsubscribe_url, prefs_url)
    html = _email_html_wrapper("", body_html, footer_html)

    text = f"""Confirm your Cloudista subscription
=====================================

Thanks for subscribing — you're one click away from getting new posts
delivered straight to your inbox.

Cloudista covers cloud infrastructure, DevOps, and platform engineering
from the field — AWS, Azure, GCP, Kubernetes, and everything in between.

Confirm your email by visiting this link:
{confirm_url}

This link expires in 72 hours.

---
You received this because someone signed up at cloudista.org.
If that wasn't you, feel free to ignore this email.

To unsubscribe: {unsubscribe_url}{(chr(10) + "Manage preferences: " + prefs_url) if prefs_url else ""}

© 2026 Cloudista
"""

    return subject, html, text


def build_digest_email(
    posts: list[dict], unsubscribe_url: str, prefs_url: str
) -> tuple[str, str, str]:
    """Return (subject, html_body, text_body) for a weekly digest email.

    Each post dict must have keys: title, slug, excerpt, image_url, published_at (datetime).
    """
    n = len(posts)
    subject = f"Cloudista — {n} new post{'s' if n != 1 else ''} this week"

    # Build post cards for HTML
    cards_html = ""
    for i, post in enumerate(posts):
        post_url = f"{_SITE_URL}/blog/{post['slug']}"
        _post_url = _html.escape(post_url, quote=True)
        _title = _html.escape(post["title"])
        excerpt = post.get("excerpt") or ""
        _excerpt = _html.escape(excerpt)
        if i > 0:
            cards_html += '<hr style="border:none;border-top:1px solid #f1f5f9;margin:24px 0;">\n'
        cards_html += f"""
              <h2 style="margin:0 0 8px;font-size:19px;font-weight:800;
                          color:#0f172a;letter-spacing:-0.03em;line-height:1.3;">
                <a href="{_post_url}" style="color:#0f172a;text-decoration:none;">{_title}</a>
              </h2>
              <p style="margin:0 0 12px;font-size:14.5px;color:#475569;line-height:1.7;">
                {_excerpt}
              </p>
              <a href="{_post_url}"
                 style="font-size:13px;color:#2563eb;text-decoration:none;font-weight:600;">
                Read more &rarr;
              </a>"""

    body_html = f"""
              <h1 style="margin:0 0 24px;font-size:24px;font-weight:900;
                          color:#0f172a;letter-spacing:-0.035em;line-height:1.15;">
                {"This week on Cloudista" if n > 1 else "New on Cloudista"}
              </h1>
              {cards_html}"""

    footer_html = _email_footer_html(unsubscribe_url, prefs_url)
    html = _email_html_wrapper("", body_html, footer_html)

    # Plain text
    text_lines = [subject, "=" * len(subject), ""]
    for post in posts:
        post_url = f"{_SITE_URL}/blog/{post['slug']}"
        excerpt = post.get("excerpt") or ""
        text_lines.append(post["title"])
        text_lines.append(post_url)
        if excerpt:
            text_lines.append(excerpt)
        text_lines.append("")
    text_lines.append(_email_footer_text(unsubscribe_url, prefs_url))
    text = "\n".join(text_lines)

    return subject, html, text


def build_immediate_email(
    post: dict, unsubscribe_url: str, prefs_url: str
) -> tuple[str, str, str]:
    """Return (subject, html_body, text_body) for a single-post immediate notification email.

    post dict must have keys: title, slug, excerpt, image_url, published_at (datetime).
    """
    subject = f"New on Cloudista: {post['title']}"
    post_url = f"{_SITE_URL}/blog/{post['slug']}"
    _post_url = _html.escape(post_url, quote=True)
    _title = _html.escape(post["title"])
    excerpt = post.get("excerpt") or ""
    _excerpt = _html.escape(excerpt)

    body_html = f"""
              <h1 style="margin:0 0 14px;font-size:26px;font-weight:900;
                          color:#0f172a;letter-spacing:-0.035em;line-height:1.15;">
                <a href="{_post_url}" style="color:#0f172a;text-decoration:none;">{_title}</a>
              </h1>
              <p style="margin:0 0 28px;font-size:15.5px;color:#475569;line-height:1.75;">
                {_excerpt}
              </p>
              <table cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="border-radius:9px;background:#2563eb;
                              box-shadow:0 4px 14px rgba(37,99,235,.35);">
                    <a href="{_post_url}" target="_blank"
                       style="display:inline-block;padding:15px 30px;
                              color:#ffffff;font-size:16px;font-weight:700;
                              text-decoration:none;letter-spacing:-0.01em;
                              border-radius:9px;line-height:1;">
                      Read the post &nbsp;&rarr;
                    </a>
                  </td>
                </tr>
              </table>"""

    footer_html = _email_footer_html(unsubscribe_url, prefs_url)
    html = _email_html_wrapper("", body_html, footer_html)

    text = f"""{subject}
{"=" * len(subject)}

{post['title']}
{post_url}

{excerpt}

{_email_footer_text(unsubscribe_url, prefs_url)}
"""

    return subject, html, text
