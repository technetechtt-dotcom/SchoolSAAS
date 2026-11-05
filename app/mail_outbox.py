"""Durable email outbox with retry for failed SMTP deliveries."""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import String, ForeignKey, DateTime, Integer, Text, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from app import main as m
from app import mailer

router = APIRouter(prefix="/api")
ADMIN = ("school_admin", "principal")
MAX_ATTEMPTS = 5


class EmailOutbox(m.Base):
    __tablename__ = "email_outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    destination: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending")  # pending|sent|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RetryIn(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)


def enqueue_email(s: Session, destination: str, subject: str, body: str,
                  school_id: int | None = None, status: str = "pending",
                  last_error: str = "") -> EmailOutbox:
    item = EmailOutbox(
        school_id=school_id, destination=destination.strip().lower(),
        subject=subject[:200], body=body, status=status, attempts=0,
        last_error=(last_error or "")[:2000])
    s.add(item)
    s.flush()
    return item


def send_or_queue(s: Session, destination: str, subject: str, body: str,
                  school_id: int | None = None) -> dict:
    """Try SMTP immediately; queue for retry when SMTP is down or send fails."""
    if not mailer.smtp_ready():
        item = enqueue_email(s, destination, subject, body, school_id,
                             status="pending", last_error="SMTP not configured")
        return {"queued": True, "sent": False, "id": item.id,
                "notice": "SMTP not configured — message queued for later delivery"}
    try:
        mailer.send_email(destination, subject, body)
        item = enqueue_email(s, destination, subject, body, school_id, status="sent")
        item.attempts = 1
        item.sent_at = datetime.now(timezone.utc)
        return {"queued": False, "sent": True, "id": item.id}
    except Exception as exc:
        item = enqueue_email(s, destination, subject, body, school_id,
                             status="failed", last_error=str(exc))
        item.attempts = 1
        return {"queued": True, "sent": False, "id": item.id,
                "notice": f"SMTP failed — queued for retry ({exc})"}


def process_outbox(s: Session, limit: int = 20, school_id: int | None = None) -> dict:
    if not mailer.smtp_ready():
        return {"processed": 0, "sent": 0, "failed": 0, "notice": "SMTP is not configured"}
    q = select(EmailOutbox).where(
        EmailOutbox.status.in_(("pending", "failed")),
        EmailOutbox.attempts < MAX_ATTEMPTS)
    if school_id is not None:
        q = q.where(EmailOutbox.school_id == school_id)
    rows = s.scalars(q.order_by(EmailOutbox.id).limit(limit)).all()
    sent = failed = 0
    for item in rows:
        item.attempts = int(item.attempts or 0) + 1
        item.updated_at = datetime.now(timezone.utc)
        try:
            mailer.send_email(item.destination, item.subject, item.body)
            item.status = "sent"
            item.sent_at = datetime.now(timezone.utc)
            item.last_error = ""
            sent += 1
        except Exception as exc:
            item.status = "failed"
            item.last_error = str(exc)[:2000]
            failed += 1
    return {"processed": len(rows), "sent": sent, "failed": failed,
            "notice": f"Retried {len(rows)} message(s): {sent} sent, {failed} still failing."}


@router.get("/mail/outbox")
def list_outbox(s: Session = Depends(m.db), ctx=Depends(m.require(*ADMIN))):
    rows = s.scalars(select(EmailOutbox).where(EmailOutbox.school_id == ctx["sid"])
                     .order_by(EmailOutbox.id.desc()).limit(100)).all()
    return {
        "items": [{
            "id": x.id, "destination": x.destination, "subject": x.subject,
            "status": x.status, "attempts": x.attempts, "last_error": x.last_error,
            "created_at": x.created_at.isoformat(),
            "sent_at": x.sent_at.isoformat() if x.sent_at else None,
        } for x in rows],
        "notice": "Queued and failed school emails. Retry sends pending/failed items (max 5 attempts).",
    }


@router.post("/mail/outbox/retry")
def retry_outbox(data: RetryIn, s: Session = Depends(m.db), ctx=Depends(m.require(*ADMIN))):
    result = process_outbox(s, limit=data.limit, school_id=ctx["sid"])
    m.log(s, ctx, "retry", "email_outbox", result["processed"])
    s.commit()
    return result
