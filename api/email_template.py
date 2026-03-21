"""
HTML + plain-text templates for the Cloudista verification email.

Usage:
    subject, html, text = build_verification_email(
        "https://cloudista.org/api/confirm/abc123",
        "https://cloudista.org/api/unsubscribe/abc123",
    )
"""
from __future__ import annotations  # enables tuple[...] hints on Python 3.8


def build_verification_email(confirm_url: str, unsubscribe_url: str) -> tuple[str, str, str]:
    """Return (subject, html_body, text_body)."""

    subject = "Confirm your Cloudista subscription"

    # ------------------------------------------------------------------
    # HTML — table-based for broad email client compatibility.
    # All CSS is inlined; no external assets required.
    # ------------------------------------------------------------------
    html = f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>Confirm your Cloudista subscription</title>
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

  <!-- Outer wrapper -->
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:#f1f5f9;min-height:100vh;">
    <tr>
      <td align="center" valign="top" style="padding:48px 16px 48px;">

        <!-- Email card -->
        <table class="email-container" cellpadding="0" cellspacing="0" border="0"
               style="width:100%;max-width:560px;">

          <!-- ── HEADER ────────────────────────────────────────────── -->
          <tr>
            <td style="border-radius:14px 14px 0 0;
                       background:linear-gradient(135deg,#2563eb 0%,#4f46e5 50%,#7c3aed 100%);
                       padding:36px 40px 32px;text-align:center;">

              <!-- Wordmark -->
              <table cellpadding="0" cellspacing="0" border="0" align="center">
                <tr>
                  <!-- Icon mark -->
                  <td style="background:rgba(255,255,255,.18);border-radius:9px;
                              padding:7px 9px 5px;vertical-align:middle;">
                    <span style="font-size:17px;line-height:1;display:block;">&#9729;</span>
                  </td>
                  <!-- Name -->
                  <td style="padding-left:9px;vertical-align:middle;">
                    <span style="color:#ffffff;font-size:20px;font-weight:800;
                                 letter-spacing:-0.03em;">Cloudista</span>
                  </td>
                </tr>
              </table>

              <!-- Tagline -->
              <p style="margin:16px 0 0;color:rgba(255,255,255,.7);
                         font-size:13px;font-weight:500;letter-spacing:0.02em;">
                All Things Cloud
              </p>
            </td>
          </tr>

          <!-- ── BODY ──────────────────────────────────────────────── -->
          <tr>
            <td class="content-pad"
                style="background:#ffffff;padding:40px 40px 36px;
                       border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">

              <!-- Heading -->
              <h1 style="margin:0 0 14px;font-size:26px;font-weight:900;
                          color:#0f172a;letter-spacing:-0.035em;line-height:1.15;">
                One click to confirm
              </h1>

              <!-- Body copy -->
              <p style="margin:0 0 14px;font-size:15.5px;color:#475569;line-height:1.75;">
                Thanks for signing up — you're almost on the Cloudista early access list.
              </p>
              <p style="margin:0 0 32px;font-size:15.5px;color:#475569;line-height:1.75;">
                Cloudista is your go-to resource for cloud tutorials, head-to-head tool
                comparisons, and daily news across AWS, Azure, GCP, and the cloud-native
                ecosystem. We'll notify you the moment we go live.
              </p>

              <!-- ── CTA button ── -->
              <!-- Bulletproof button via VML for Outlook -->
              <!--[if mso]>
              <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml"
                           xmlns:w="urn:schemas-microsoft-com:office:word"
                           href="{confirm_url}"
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
                    <a href="{confirm_url}" target="_blank"
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

              <!-- Divider -->
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="border-top:1px solid #f1f5f9;padding-top:24px;">
                    <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;">
                      Button not working? Copy and paste this URL into your browser:
                    </p>
                    <p style="margin:0;font-size:11.5px;word-break:break-all;line-height:1.6;">
                      <a href="{confirm_url}"
                         style="color:#2563eb;text-decoration:none;">{confirm_url}</a>
                    </p>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- ── FOOTER ─────────────────────────────────────────────── -->
          <tr>
            <td class="footer-pad"
                style="background:#f8fafc;
                       border:1px solid #e2e8f0;border-top:none;
                       border-radius:0 0 14px 14px;
                       padding:20px 40px;text-align:center;">

              <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;line-height:1.65;">
                You received this email because someone signed up at
                <a href="https://cloudista.org"
                   style="color:#64748b;text-decoration:none;">cloudista.org</a>.
                If that wasn't you, you can safely ignore this email or
                <a href="{unsubscribe_url}"
                   style="color:#64748b;text-decoration:none;">unsubscribe</a>.
              </p>
              <p style="margin:0;font-size:12px;color:#cbd5e1;">
                &copy; 2026 Cloudista &nbsp;&middot;&nbsp; All rights reserved
              </p>

            </td>
          </tr>

        </table>
        <!-- /email card -->

      </td>
    </tr>
  </table>

</body>
</html>"""

    # ------------------------------------------------------------------
    # Plain text fallback
    # ------------------------------------------------------------------
    text = f"""Confirm your Cloudista subscription
=====================================

Thanks for signing up — you're almost on the Cloudista early access list.

Cloudista is your go-to resource for cloud tutorials, head-to-head tool
comparisons, and daily news across AWS, Azure, GCP, and the cloud-native
ecosystem. We'll notify you the moment we go live.

Confirm your email by visiting this link:
{confirm_url}

This link expires in 72 hours.

---
You received this because someone signed up at cloudista.org.
If that wasn't you, feel free to ignore this email.

To unsubscribe: {unsubscribe_url}

© 2026 Cloudista
"""

    return subject, html, text
