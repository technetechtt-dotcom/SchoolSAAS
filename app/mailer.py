"""Shared SMTP delivery for recovery, invitations and parent notices."""
from __future__ import annotations
import os, ssl, smtplib
from email.message import EmailMessage


def smtp_ready() -> bool:
    return all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "APP_PUBLIC_URL"))


def public_url(path: str = "") -> str:
    base = (os.environ.get("APP_PUBLIC_URL") or "http://127.0.0.1:8000").rstrip("/")
    if not path:
        return base
    return base + (path if path.startswith("/") else "/" + path)


def send_email(destination: str, subject: str, body: str) -> None:
    if not smtp_ready():
        raise RuntimeError("SMTP is not configured")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = destination
    msg.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "465")), timeout=10, context=context) as smtp:
        smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)
