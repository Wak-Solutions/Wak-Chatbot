"""
email_service.py — Gmail SMTP email sender for the WAK Solutions chatbot service.

Reads GMAIL_ADDRESS and GMAIL_APP_PASSWORD from environment variables.
Uses Python's built-in smtplib only — no third-party packages required.
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

_DISPLAY_NAME = "WAK Solutions"
_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587


def send_email(to: str, subject: str, html_body: str) -> bool:
    """
    Send an HTML email via Gmail SMTP.

    Returns True on success, False on failure — never raises, so a failed
    email never crashes the caller's flow.

    Env vars required:
      GMAIL_ADDRESS       — the sending Gmail address
      GMAIL_APP_PASSWORD  — a Gmail App Password (not the account password)
    """
    gmail_address = os.environ.get("GMAIL_ADDRESS", "").strip()
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

    print(f"Gmail config: GMAIL_ADDRESS set={bool(gmail_address)}, GMAIL_APP_PASSWORD set={bool(app_password)}", flush=True)
    print(f"EMAIL ATTEMPT: to={to}", flush=True)

    if not gmail_address or not app_password:
        logger.warning(
            "[WARN] [email_service] GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set — email not sent"
        )
        print("EMAIL ERROR: missing Gmail credentials", flush=True)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{_DISPLAY_NAME} <{gmail_address}>"
    msg["To"] = to

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(gmail_address, app_password)
            smtp.sendmail(gmail_address, to, msg.as_string())
        logger.info("[INFO] [email_service] Email sent — to: %s, subject: %s", to, subject)
        print(f"EMAIL SUCCESS: to={to}", flush=True)
        return True
    except smtplib.SMTPAuthenticationError as exc:
        logger.error(
            "[ERROR] [email_service] SMTP authentication failed — check GMAIL_APP_PASSWORD"
        )
        print(f"EMAIL ERROR: SMTPAuthenticationError — {exc}", flush=True)
        return False
    except smtplib.SMTPRecipientsRefused as exc:
        logger.error(
            "[ERROR] [email_service] Recipient refused — to: %s", to
        )
        print(f"EMAIL ERROR: SMTPRecipientsRefused — to={to}, error={exc}", flush=True)
        return False
    except Exception as exc:
        logger.error("[ERROR] [email_service] Failed to send email — to: %s, error: %s", to, exc)
        print(f"EMAIL ERROR: {type(exc).__name__} — {exc}", flush=True)
        return False


def build_booking_confirmation_html(
    customer_name: str,
    meeting_time: str,
    meeting_link: str,
    agent_name: str = "Our team",
) -> str:
    """Return an HTML email body for a meeting booking confirmation."""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
</head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:32px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:12px;overflow:hidden;
                      box-shadow:0 2px 8px rgba(0,0,0,0.08);max-width:600px;width:100%;">

          <!-- Header -->
          <tr>
            <td style="background:#0F510F;padding:28px 32px;">
              <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;
                         letter-spacing:-0.3px;">WAK Solutions</h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.75);font-size:13px;">
                Meeting Confirmation
              </p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:32px;">
              <p style="margin:0 0 16px;color:#1a1a1a;font-size:16px;">
                Hi <strong>{customer_name}</strong>,
              </p>
              <p style="margin:0 0 24px;color:#444;font-size:15px;line-height:1.6;">
                Your meeting with WAK Solutions has been confirmed. Here are the details:
              </p>

              <!-- Details card -->
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#f8faf8;border:1px solid #d4e8d4;
                            border-radius:8px;margin-bottom:28px;">
                <tr>
                  <td style="padding:20px 24px;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="padding:6px 0;color:#555;font-size:13px;
                                   width:120px;vertical-align:top;">
                          <strong>Date &amp; Time</strong>
                        </td>
                        <td style="padding:6px 0;color:#1a1a1a;font-size:13px;">
                          {meeting_time}
                        </td>
                      </tr>
                      <tr>
                        <td style="padding:6px 0;color:#555;font-size:13px;vertical-align:top;">
                          <strong>Host</strong>
                        </td>
                        <td style="padding:6px 0;color:#1a1a1a;font-size:13px;">
                          {agent_name}
                        </td>
                      </tr>
                      <tr>
                        <td style="padding:6px 0;color:#555;font-size:13px;vertical-align:top;">
                          <strong>Meeting link</strong>
                        </td>
                        <td style="padding:6px 0;font-size:13px;">
                          <a href="{meeting_link}"
                             style="color:#0F510F;text-decoration:underline;
                                    word-break:break-all;">{meeting_link}</a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- CTA button -->
              <table cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
                <tr>
                  <td style="background:#0F510F;border-radius:8px;">
                    <a href="{meeting_link}"
                       style="display:inline-block;padding:12px 28px;color:#ffffff;
                              font-size:14px;font-weight:600;text-decoration:none;
                              letter-spacing:0.2px;">
                      Join Meeting
                    </a>
                  </td>
                </tr>
              </table>

              <p style="margin:0;color:#777;font-size:13px;line-height:1.6;">
                The meeting link will also be sent to you on WhatsApp 15 minutes before
                the start time. If you need to reschedule, please reply to this email or
                contact us on WhatsApp.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#f8f8f8;border-top:1px solid #eee;
                       padding:16px 32px;text-align:center;">
              <p style="margin:0;color:#aaa;font-size:12px;">
                &copy; {_get_year()} WAK Solutions &mdash; All rights reserved
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
""".strip()


def _get_year() -> int:
    from datetime import datetime
    return datetime.now().year
