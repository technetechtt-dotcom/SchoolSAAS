"""Approved letter drafts, PDF generation and delivery tracking."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import os, re, secrets
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import String, ForeignKey, DateTime, Text, Integer, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from app import main as m
from app.pilot_pack import LetterTemplate
from app import mailer

router = APIRouter(prefix="/api")
MANAGERS = ("school_admin", "principal", "smt", "hod")
LETTER_ROOT = Path(os.getenv("LETTER_UPLOAD_DIR", "./uploads/letters")).resolve()


class LetterDocument(m.Base):
    __tablename__ = "letter_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("letter_templates.id"), nullable=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="draft")  # draft|approved|delivered|failed
    delivery_channel: Mapped[str] = mapped_column(String(40), default="none")
    delivery_to: Mapped[str] = mapped_column(String(255), default="")
    delivery_notes: Mapped[str] = mapped_column(Text, default="")
    stored_pdf: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class LetterCreateIn(BaseModel):
    template_id: int | None = None
    learner_id: int
    title: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=5, max_length=50000)


class LetterDeliverIn(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    channel: str = Field(default="email", max_length=40)


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def render_simple_pdf(title: str, body: str) -> bytes:
    """Minimal single-page PDF without external dependencies."""
    lines = []
    lines.append(title.strip()[:120] or "SchoolCare letter")
    lines.append("")
    for paragraph in body.replace("\r\n", "\n").split("\n"):
        chunk = paragraph.strip() or " "
        while chunk:
            lines.append(chunk[:90])
            chunk = chunk[90:]
    lines = lines[:48]
    content_lines = ["BT", "/F1 11 Tf", "50 780 Td", "14 TL"]
    first = True
    for line in lines:
        esc = _pdf_escape(line)
        if first:
            content_lines.append(f"({esc}) Tj")
            first = False
        else:
            content_lines.append("T*")
            content_lines.append(f"({esc}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")
    objs = []
    objs.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objs.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objs.append(b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n")
    objs.append(f"4 0 obj<< /Length {len(stream)} >>stream\n".encode() + stream + b"\nendstream\nendobj\n")
    objs.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)
    xref = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode())
    out.extend(f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(out)


def _out(x: LetterDocument):
    return {
        "id": x.id, "template_id": x.template_id, "learner_id": x.learner_id, "title": x.title,
        "body": x.body, "status": x.status, "delivery_channel": x.delivery_channel,
        "delivery_to": x.delivery_to, "delivery_notes": x.delivery_notes,
        "has_pdf": bool(x.stored_pdf), "created_by": x.created_by, "approved_by": x.approved_by,
        "created_at": x.created_at.isoformat(), "updated_at": x.updated_at.isoformat(),
    }


@router.get("/letter-documents")
def list_letters(s: Session = Depends(m.db), ctx=Depends(m.require(*MANAGERS))):
    rows = s.scalars(select(LetterDocument).where(LetterDocument.school_id == ctx["sid"])
                     .order_by(LetterDocument.id.desc()).limit(200)).all()
    return [_out(x) for x in rows]


@router.post("/letter-documents", status_code=201)
def create_letter(data: LetterCreateIn, s: Session = Depends(m.db), ctx=Depends(m.require(*MANAGERS))):
    learner = s.scalar(select(m.Learner).where(m.Learner.id == data.learner_id, m.Learner.school_id == ctx["sid"]))
    if not learner:
        raise HTTPException(404, "Learner not found")
    body = data.body
    title = data.title
    template_id = data.template_id
    if template_id:
        tpl = s.scalar(select(LetterTemplate).where(LetterTemplate.id == template_id, LetterTemplate.school_id == ctx["sid"]))
        if not tpl:
            raise HTTPException(404, "Template not found")
        title = title or tpl.name
        body = (tpl.body
                .replace("{{learner_name}}", f"{learner.first_name} {learner.surname}")
                .replace("{{grade}}", learner.grade)
                .replace("{{class_name}}", learner.class_name)
                .replace("{{school}}", ctx["school"])
                .replace("{{date}}", datetime.now(timezone.utc).date().isoformat()))
    item = LetterDocument(school_id=ctx["sid"], template_id=template_id, learner_id=learner.id,
                          title=title.strip(), body=body, status="draft", created_by=ctx["uid"])
    s.add(item); s.flush(); m.log(s, ctx, "create", "letter_document", item.id); s.commit()
    return {"id": item.id, "status": item.status}


@router.post("/letter-documents/{letter_id}/approve")
def approve_letter(letter_id: int, s: Session = Depends(m.db),
                   ctx=Depends(m.require("school_admin", "principal", "smt"))):
    item = s.scalar(select(LetterDocument).where(LetterDocument.id == letter_id, LetterDocument.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Letter not found")
    if item.status not in {"draft", "failed"}:
        raise HTTPException(409, "Only draft letters can be approved")
    pdf = render_simple_pdf(item.title, item.body)
    folder = LETTER_ROOT / str(ctx["sid"])
    folder.mkdir(parents=True, exist_ok=True)
    stored = secrets.token_hex(16) + ".pdf"
    (folder / stored).write_bytes(pdf)
    item.stored_pdf = stored
    item.status = "approved"
    item.approved_by = ctx["uid"]
    item.updated_at = datetime.now(timezone.utc)
    m.log(s, ctx, "approve", "letter_document", item.id); s.commit()
    return {"id": item.id, "status": item.status, "has_pdf": True}


@router.get("/letter-documents/{letter_id}/pdf")
def download_letter_pdf(letter_id: int, s: Session = Depends(m.db), ctx=Depends(m.require(*MANAGERS))):
    item = s.scalar(select(LetterDocument).where(LetterDocument.id == letter_id, LetterDocument.school_id == ctx["sid"]))
    if not item or not item.stored_pdf:
        raise HTTPException(404, "Approved PDF not found")
    path = LETTER_ROOT / str(item.school_id) / item.stored_pdf
    if not path.is_file():
        raise HTTPException(404, "PDF missing from storage")
    m.log(s, ctx, "download", "letter_document", item.id); s.commit()
    return Response(path.read_bytes(), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="letter-{item.id}.pdf"'})


@router.post("/letter-documents/{letter_id}/deliver")
def deliver_letter(letter_id: int, data: LetterDeliverIn, s: Session = Depends(m.db),
                   ctx=Depends(m.require(*MANAGERS))):
    from app.onboarding import assert_onboarding_complete
    assert_onboarding_complete(s, ctx, "delivering formal letters")
    item = s.scalar(select(LetterDocument).where(LetterDocument.id == letter_id, LetterDocument.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Letter not found")
    if item.status != "approved":
        raise HTTPException(409, "Approve the letter before delivery")
    email = data.email.lower().strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(400, "Invalid delivery email")
    item.delivery_to = email
    item.delivery_channel = data.channel
    if mailer.smtp_ready():
        try:
            mailer.send_email(email, item.title, item.body)
            item.status = "delivered"
            item.delivery_notes = "Emailed via SMTP"
        except Exception as exc:
            item.status = "failed"
            item.delivery_notes = f"SMTP delivery failed: {exc}"
            m.log(s, ctx, "deliver_failed", "letter_document", item.id); s.commit()
            raise HTTPException(503, "Letter email delivery failed")
    else:
        item.status = "approved"
        item.delivery_notes = "SMTP not configured — mark for manual hand delivery"
        m.log(s, ctx, "deliver_manual", "letter_document", item.id); s.commit()
        return {"id": item.id, "status": item.status, "notice": item.delivery_notes, "manual": True}
    item.updated_at = datetime.now(timezone.utc)
    m.log(s, ctx, "deliver", "letter_document", item.id); s.commit()
    return {"id": item.id, "status": item.status, "manual": False}
