"""Platform-aware email sender for Grafana Reporter PDF reports."""

import platform
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from app import config_manager


def send(
    to_contacts: list[dict[str, Any]],
    subject: str,
    attachments: list,
    custom_message: str = "",
) -> None:
    """Send all attachments to all contacts, choosing the appropriate mail method.

    Priority:
    1. force_smtp=true in config → SMTP directly, Outlook skipped.
    2. Windows + force_smtp=false → try win32com Outlook first.
    3. win32com fails → fall back to SMTP automatically.
    4. SMTP host empty → raises RuntimeError with a clear message.
    Does nothing if to_contacts is empty.
    """
    if not to_contacts:
        return

    smtp = config_manager.get_smtp_settings()
    force_smtp = smtp.get("force_smtp", False)

    if force_smtp:
        _smtp_send(to_contacts, subject, attachments, custom_message)
        return

    if platform.system() == "Windows":
        try:
            _outlook_send(to_contacts, subject, attachments, custom_message)
            return
        except Exception as e:
            print(f"[mailer] win32com failed ({e}), falling back to SMTP")
            _smtp_send(to_contacts, subject, attachments, custom_message)
            return

    _smtp_send(to_contacts, subject, attachments, custom_message)


# ---------------------------------------------------------------------------
# HTML body
# ---------------------------------------------------------------------------

def _html_body(name: str = "", custom_message: str = "") -> str:
    """Return a clean minimal HTML email body, optionally personalised with name and message."""
    greeting = f"Hello {name}," if name else "Hello,"
    msg_block = ""
    if custom_message:
        msg_block = (
            '<p style="margin:16px 0; padding:12px; '
            'background:#f5f5f5; border-left:3px solid #ccc;">'
            f"{custom_message}</p>"
        )
    return f"""\
<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; font-size: 14px; color: #333333;
             margin: 0; padding: 24px; max-width: 600px;">
  <p style="margin-top: 0;">{greeting}</p>
  <p>Please find attached your scheduled Grafana report.</p>
  {msg_block}
  <p>The full report is included as an attachment.</p>
  <br>
  <hr style="border: none; border-top: 1px solid #eeeeee; margin: 16px 0;">
  <p style="color: #888888; font-size: 12px; margin-bottom: 0;">
    &mdash;&nbsp;Grafana Reporter
  </p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Windows — Outlook via win32com
# ---------------------------------------------------------------------------

def _outlook_send(
    to_contacts: list[dict[str, Any]],
    subject: str,
    attachments: list,
    custom_message: str = "",
) -> None:
    """Send via the local Outlook application using win32com (Windows only).

    All recipients are placed in the To field as semicolon-separated
    'Name <email>' strings and receive a single shared email.
    Raises RuntimeError if Outlook is not available or the send fails.
    """
    try:
        import win32com.client  # available only on Windows with pywin32
    except ImportError as exc:
        raise RuntimeError(
            "pywin32 is not installed — cannot use Outlook on this machine."
        ) from exc

    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # 0 = olMailItem

        mail.To = "; ".join(
            f"{c['name']} <{c['email']}>" for c in to_contacts
        )
        mail.Subject = subject
        mail.HTMLBody = _html_body(
            to_contacts[0]["name"] if to_contacts else "",
            custom_message,
        )
        for att in attachments:
            mail.Attachments.Add(str(Path(att).resolve()))
        mail.Send()
    except Exception as exc:
        raise RuntimeError(f"Outlook send failed: {exc}") from exc


# ---------------------------------------------------------------------------
# SMTP — internal relay (port 25) or external with STARTTLS (port 587+)
# ---------------------------------------------------------------------------

def _smtp_send(
    to_contacts: list[dict[str, Any]],
    subject: str,
    attachments: list,
    custom_message: str = "",
) -> None:
    """Send via SMTP, one individually addressed email per contact.

    Port 25 (or no credentials): internal relay — no auth, no TLS.
    Any other port with credentials: STARTTLS + login (Gmail, Mailtrap, etc).
    Raises RuntimeError if host is not configured or the connection fails.
    """
    smtp = config_manager.get_smtp_settings()
    host = smtp.get("host", "")
    port = smtp.get("port", 587)
    username = smtp.get("username", "")
    password = smtp.get("password", "")
    tls_mode = smtp.get("tls_mode", "auto")

    if not host:
        raise RuntimeError(
            "No email method available. On Windows: ensure Outlook is "
            "installed and open, OR configure SMTP settings. "
            "Ask IT for the internal SMTP relay address."
        )

    if tls_mode == "auto":
        raise RuntimeError(
            "TLS Mode is set to Auto. "
            "Please go to Settings → SMTP Settings and "
            "explicitly select a TLS mode: "
            "STARTTLS, SSL/TLS, or None."
        )

    try:
        if tls_mode == "ssl":
            import ssl
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
                server.ehlo()
                if username and password:
                    server.login(username, password)
                for contact in to_contacts:
                    msg = _build_mime(contact, subject, attachments, from_addr=username, custom_message=custom_message)
                    server.send_message(msg)
        elif tls_mode == "starttls":
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if username and password:
                    server.login(username, password)
                for contact in to_contacts:
                    msg = _build_mime(contact, subject, attachments, from_addr=username, custom_message=custom_message)
                    server.send_message(msg)
        else:
            # Plain SMTP — no TLS, no auth (internal relay / port 25)
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.ehlo()
                for contact in to_contacts:
                    msg = _build_mime(contact, subject, attachments, custom_message=custom_message)
                    server.send_message(msg)
    except smtplib.SMTPException as exc:
        raise RuntimeError(f"SMTP send failed: {exc}") from exc


# ---------------------------------------------------------------------------
# MIME builder
# ---------------------------------------------------------------------------

def _build_mime(
    contact: dict[str, Any],
    subject: str,
    attachments: list,
    from_addr: str = "",
    custom_message: str = "",
) -> MIMEMultipart:
    """Build a MIMEMultipart email with an HTML body and one or more file attachments."""
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = f"{contact['name']} <{contact['email']}>"

    msg.attach(MIMEText(_html_body(contact.get("name", ""), custom_message), "html", "utf-8"))

    for att_path in attachments:
        part = MIMEApplication(Path(att_path).read_bytes())
        part["Content-Disposition"] = f'attachment; filename="{Path(att_path).name}"'
        msg.attach(part)

    return msg
