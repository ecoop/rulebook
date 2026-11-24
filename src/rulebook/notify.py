# Copyright (c) 2026 Eric Cooper.
"""Outgoing email: tell the operator about a new join request (#337).

SMTP with STARTTLS, Gmail by default (an app password, held in Secret Manager
on Cloud Run). Email is optional: with no SMTP user/password configured,
`email_configured()` is False and sends are skipped with a log line.

`send_email` raises on failure; callers on a request path use
`notify_join_request`, which logs and swallows so a mail outage never fails
the request that triggered it.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import settings

log = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 15


def email_configured() -> bool:
    return bool(settings.smtp_user and settings.smtp_password)


def notify_recipient() -> str | None:
    return settings.notify_email or settings.smtp_user


def send_email(*, to: str, subject: str, body: str) -> None:
    """Send one plain-text email. Raises if email isn't configured or the send fails."""
    if not email_configured():
        raise RuntimeError("email is not configured (RULEBOOK_SMTP_USER / RULEBOOK_SMTP_PASSWORD)")
    msg = EmailMessage()
    msg["From"] = settings.smtp_user
    msg["To"] = to
    # Header values come partly from the public form; EmailMessage refuses
    # embedded newlines, and the request fields are single-line already.
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def _users_tab_link() -> str | None:
    if not settings.public_url:
        return None
    return settings.public_url.rstrip("/") + "/#/activity"


def join_request_email(record: dict, pending: int) -> tuple[str, str]:
    """(subject, body) for a new-request alert. Pure, for testing."""
    subject = f"Rulebook join request: {record['name']}"
    lines = [
        f"{record['name']} asked to join Rulebook.",
        "",
        f"Email: {record['email']}",
        f"How they heard about Rulebook: {record['heard_about']}",
        f"Source: {record.get('source', 'web')}",
    ]
    if record.get("referred_by"):
        lines.append(f"Referred by: {record['referred_by']}")
    lines += ["", f"Requests waiting: {pending}"]
    link = _users_tab_link()
    if link:
        lines += ["", f"Review it in the Users tab: {link}"]
    return subject, "\n".join(lines) + "\n"


def notify_join_request(record: dict, pending: int) -> bool:
    """Email the operator about a new request. Never raises; True if sent."""
    to = notify_recipient()
    if not email_configured() or not to:
        log.info("notify: email not configured; skipping join-request alert for %s", record.get("id"))
        return False
    subject, body = join_request_email(record, pending)
    try:
        send_email(to=to, subject=subject, body=body)
    except Exception:  # noqa: BLE001 — a mail outage must not fail the request
        log.exception("notify: failed to send join-request alert for %s", record.get("id"))
        return False
    return True
