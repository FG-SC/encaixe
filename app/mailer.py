"""Outgoing e-mail (login links; later, match notices) over SMTP from the standard library.

Without SMTP configured (development), a message is not sent: it is logged and kept in ``OUTBOX`` so tests and the
local demo can follow the link. Production refuses to start without SMTP (``Settings.prod_problems``).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger(__name__)

OUTBOX: list[dict[str, str]] = []
TIMEOUT_SECONDS = 10


def send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.smtp_host:
        log.warning("e-mail not sent (no SMTP configured) to %s: %s\n%s", to, subject, body)
        OUTBOX.append({"to": to, "subject": subject, "body": body})
        return
    msg = EmailMessage()
    msg["From"] = s.smtp_from or s.smtp_user or ""
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    context = ssl.create_default_context()
    if s.smtp_port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=TIMEOUT_SECONDS, context=context)
    else:
        server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=TIMEOUT_SECONDS)
        server.starttls(context=context)
    with server:
        if s.smtp_user:
            server.login(s.smtp_user, s.smtp_password or "")
        server.send_message(msg)
