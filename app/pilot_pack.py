"""v0.6 pilot foundation: MFA, CoC versions, hearings, evidence, parent links, platform admin, billing stubs."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib, os, secrets
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Response
from pydantic import BaseModel, Field
from sqlalchemy import String, ForeignKey, DateTime, Boolean, Text, Integer, UniqueConstraint, select, func
from sqlalchemy.orm import Session, Mapped, mapped_column
from app import main as m
from app import mailer

try:
    import pyotp
except ImportError:  # pragma: no cover
    pyotp = None

router = APIRouter(prefix="/api")
UPLOAD_ROOT = Path(os.getenv("EVIDENCE_UPLOAD_DIR", "./uploads")).resolve()
MAX_UPLOAD_BYTES = int(os.getenv("EVIDENCE_MAX_BYTES", str(5 * 1024 * 1024)))


# --- models -----------------------------------------------------------------
class ConductVersion(m.Base):
    __tablename__ = "conduct_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    version_label: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Hearing(m.Base):
    __tablename__ = "hearings"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    chair: Mapped[str] = mapped_column(String(120))
    outcome: Mapped[str] = mapped_column(String(200), default="pending")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="scheduled")


class EvidenceFile(m.Base):
    __tablename__ = "evidence_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), nullable=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(200))
    stored_name: Mapped[str] = mapped_column(String(80))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class LetterTemplate(m.Base):
    __tablename__ = "letter_templates"
    __table_args__ = (UniqueConstraint("school_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)


class ParentAccess(m.Base):
    __tablename__ = "parent_access_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    email: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class ParentAck(m.Base):
    __tablename__ = "parent_acknowledgements"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    email: Mapped[str] = mapped_column(String(255))


class Invoice(m.Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="ZAR")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    description: Mapped[str] = mapped_column(String(200), default="SchoolCare subscription")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RetentionPolicy(m.Base):
    __tablename__ = "retention_policies"
    __table_args__ = (UniqueConstraint("school_id", "record_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    record_type: Mapped[str] = mapped_column(String(60))
    retain_days: Mapped[int] = mapped_column(Integer, default=2555)  # ~7 years default guidance placeholder
    notes: Mapped[str] = mapped_column(String(300), default="")


# --- helpers ----------------------------------------------------------------
def _require_pyotp():
    if pyotp is None:
        raise HTTPException(503, "MFA library not installed (pyotp)")


def platform_admins() -> set[str]:
    raw = os.getenv("PLATFORM_ADMIN_EMAILS", "")
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def platform_user(s: Session, ctx: dict):
    user = s.get(m.User, ctx["uid"])
    if not user or user.email not in platform_admins():
        raise HTTPException(403, "Platform administrator access required")
    return user


def issue_mfa_pending(uid: int, school_id: int) -> str:
    return m.jwt.encode(
        {"sub": str(uid), "school_id": school_id, "purpose": "mfa",
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        m.JWT_SECRET, algorithm="HS256")


def decode_mfa_pending(token: str):
    try:
        payload = m.jwt.decode(token, m.JWT_SECRET, algorithms=["HS256"])
        if payload.get("purpose") != "mfa":
            raise ValueError("bad purpose")
        return int(payload["sub"]), int(payload["school_id"])
    except Exception:
        raise HTTPException(401, "MFA challenge expired or invalid")


# --- schemas ----------------------------------------------------------------
class MfaConfirm(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class MfaLogin(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=8)


class ConductIn(BaseModel):
    version_label: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=50000)
    effective_from: str


class HearingIn(BaseModel):
    case_id: int
    scheduled_at: str
    chair: str = Field(min_length=2, max_length=120)
    notes: str = Field(default="", max_length=4000)


class HearingPatch(BaseModel):
    status: str = Field(min_length=2, max_length=40)
    outcome: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=4000)


class TemplateIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    body: str = Field(min_length=5, max_length=20000)


class ParentInviteIn(BaseModel):
    learner_id: int
    email: str = Field(min_length=5, max_length=255)
    subject: str = Field(default="SchoolCare notice", max_length=200)


class ParentAckIn(BaseModel):
    token: str
    subject: str = Field(min_length=3, max_length=200)


class InvoiceIn(BaseModel):
    amount_cents: int = Field(ge=100)
    description: str = Field(default="SchoolCare subscription", max_length=200)


class RetentionIn(BaseModel):
    record_type: str = Field(min_length=2, max_length=60)
    retain_days: int = Field(ge=30, le=36500)
    notes: str = Field(default="", max_length=300)


class SchoolStatusIn(BaseModel):
    school_id: int
    status: str
    plan: str | None = None


# --- MFA --------------------------------------------------------------------
@router.post("/mfa/setup")
def mfa_setup(s: Session = Depends(m.db), ctx=Depends(m.current)):
    _require_pyotp()
    user = s.get(m.User, ctx["uid"])
    if not user:
        raise HTTPException(404, "User not found")
    secret = pyotp.random_base32()
    user.mfa_secret = secret
    user.mfa_enabled = False
    s.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="SchoolCare")
    return {"secret": secret, "otpauth_uri": uri, "message": "Confirm with /api/mfa/enable using a current code"}


@router.post("/mfa/enable")
def mfa_enable(data: MfaConfirm, s: Session = Depends(m.db), ctx=Depends(m.current)):
    _require_pyotp()
    user = s.get(m.User, ctx["uid"])
    if not user or not user.mfa_secret:
        raise HTTPException(400, "Run MFA setup first")
    if not pyotp.TOTP(user.mfa_secret).verify(data.code, valid_window=1):
        raise HTTPException(401, "Invalid MFA code")
    user.mfa_enabled = True
    s.commit()
    return {"ok": True, "mfa_enabled": True}


@router.post("/mfa/disable")
def mfa_disable(data: MfaConfirm, s: Session = Depends(m.db), ctx=Depends(m.current)):
    _require_pyotp()
    user = s.get(m.User, ctx["uid"])
    if not user or not user.mfa_enabled or not user.mfa_secret:
        return {"ok": True, "mfa_enabled": False}
    if not pyotp.TOTP(user.mfa_secret).verify(data.code, valid_window=1):
        raise HTTPException(401, "Invalid MFA code")
    user.mfa_enabled = False
    user.mfa_secret = None
    s.commit()
    return {"ok": True, "mfa_enabled": False}


@router.post("/mfa/verify-login")
def mfa_verify_login(data: MfaLogin, response: Response, s: Session = Depends(m.db)):
    _require_pyotp()
    uid, sid = decode_mfa_pending(data.mfa_token)
    user = s.get(m.User, uid)
    if not user or not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(400, "MFA not enabled")
    if not pyotp.TOTP(user.mfa_secret).verify(data.code, valid_window=1):
        raise HTTPException(401, "Invalid MFA code")
    mem = s.scalar(select(m.Membership).where(m.Membership.user_id == uid, m.Membership.school_id == sid))
    school = s.get(m.School, sid)
    if not mem or not mem.active or not school:
        raise HTTPException(403, "School access denied")
    token = m.issue_token(uid, sid, s)
    s.commit()
    response.set_cookie("session", token, httponly=True,
                        secure=os.getenv("COOKIE_SECURE", "false") == "true",
                        samesite="lax", max_age=28800)
    return {"school": school.name, "role": mem.role, "mfa_ok": True}


# --- Code of Conduct --------------------------------------------------------
@router.get("/conduct-versions")
def list_conduct(s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    rows = s.scalars(select(ConductVersion).where(ConductVersion.school_id == ctx["sid"]).order_by(ConductVersion.id.desc())).all()
    return [{"id": x.id, "version_label": x.version_label, "title": x.title, "effective_from": x.effective_from.isoformat(),
             "approved": x.approved} for x in rows]


@router.post("/conduct-versions", status_code=201)
def add_conduct(data: ConductIn, s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal"))):
    try:
        effective = datetime.fromisoformat(data.effective_from.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "effective_from must be ISO datetime")
    item = ConductVersion(school_id=ctx["sid"], version_label=data.version_label, title=data.title,
                          body=data.body, effective_from=effective, approved=False)
    s.add(item); s.flush(); m.log(s, ctx, "create", "conduct_version", item.id); s.commit()
    return {"id": item.id}


@router.patch("/conduct-versions/{version_id}/approve")
def approve_conduct(version_id: int, s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal"))):
    item = s.scalar(select(ConductVersion).where(ConductVersion.id == version_id, ConductVersion.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Conduct version not found")
    item.approved = True
    m.log(s, ctx, "approve", "conduct_version", item.id); s.commit()
    return {"id": item.id, "approved": True}


@router.get("/conduct-versions/{version_id}")
def get_conduct(version_id: int, s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    item = s.scalar(select(ConductVersion).where(ConductVersion.id == version_id, ConductVersion.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Conduct version not found")
    return {"id": item.id, "version_label": item.version_label, "title": item.title, "body": item.body,
            "effective_from": item.effective_from.isoformat(), "approved": item.approved}


# --- Hearings ---------------------------------------------------------------
@router.get("/hearings")
def list_hearings(s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    rows = s.scalars(select(Hearing).where(Hearing.school_id == ctx["sid"]).order_by(Hearing.scheduled_at.desc())).all()
    return [{"id": x.id, "case_id": x.case_id, "scheduled_at": x.scheduled_at.isoformat(), "chair": x.chair,
             "status": x.status, "outcome": x.outcome} for x in rows]


@router.post("/hearings", status_code=201)
def add_hearing(data: HearingIn, s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal", "smt"))):
    case = s.scalar(select(m.Case).where(m.Case.id == data.case_id, m.Case.school_id == ctx["sid"]))
    if not case:
        raise HTTPException(404, "Case not found")
    try:
        when = datetime.fromisoformat(data.scheduled_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "scheduled_at must be ISO datetime")
    item = Hearing(school_id=ctx["sid"], case_id=data.case_id, scheduled_at=when, chair=data.chair, notes=data.notes)
    s.add(item); s.flush(); m.log(s, ctx, "create", "hearing", item.id); s.commit()
    return {"id": item.id}


@router.patch("/hearings/{hearing_id}")
def patch_hearing(hearing_id: int, data: HearingPatch, s: Session = Depends(m.db),
                  ctx=Depends(m.require("school_admin", "principal", "smt"))):
    item = s.scalar(select(Hearing).where(Hearing.id == hearing_id, Hearing.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Hearing not found")
    item.status = data.status
    if data.outcome:
        item.outcome = data.outcome
    if data.notes:
        item.notes = data.notes
    m.log(s, ctx, "update", "hearing", item.id); s.commit()
    return {"id": item.id, "status": item.status, "outcome": item.outcome}


# --- Evidence ---------------------------------------------------------------
@router.post("/evidence", status_code=201)
async def upload_evidence(incident_id: int | None = Form(None), case_id: int | None = Form(None),
                          file: UploadFile = File(...), s: Session = Depends(m.db),
                          ctx=Depends(m.require("school_admin", "principal", "smt", "hod", "educator"))):
    if not incident_id and not case_id:
        raise HTTPException(400, "Provide incident_id or case_id")
    if ctx["role"] == "educator":
        if case_id:
            raise HTTPException(403, "Educators cannot upload evidence directly to cases")
        incident = s.scalar(select(m.Incident).where(
            m.Incident.id == incident_id, m.Incident.school_id == ctx["sid"],
            m.Incident.reporter_id == ctx["uid"]))
        if not incident:
            raise HTTPException(403, "Only the reporting educator may attach evidence to their incident")
        learner = s.scalar(select(m.Learner).where(
            m.Learner.id == incident.learner_id,m.Learner.school_id == ctx["sid"]))
        if not learner or learner.class_name not in ctx["assigned_classes"]:
            raise HTTPException(403, "Learner is outside your assigned classes")
    if incident_id:
        if not s.scalar(select(m.Incident).where(m.Incident.id == incident_id, m.Incident.school_id == ctx["sid"])):
            raise HTTPException(404, "Incident not found")
    if case_id:
        if not s.scalar(select(m.Case).where(m.Case.id == case_id, m.Case.school_id == ctx["sid"])):
            raise HTTPException(404, "Case not found")
    approved_types={"application/pdf","image/png","image/jpeg","text/plain"}
    if file.content_type not in approved_types:
        raise HTTPException(415, "Unsupported evidence type")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"File exceeds {MAX_UPLOAD_BYTES} bytes")
    if not raw:
        raise HTTPException(400, "Empty file")
    folder = UPLOAD_ROOT / str(ctx["sid"])
    folder.mkdir(parents=True, exist_ok=True)
    stored = secrets.token_hex(16)
    (folder / stored).write_bytes(raw)
    name = (file.filename or "evidence.bin")[:200]
    item = EvidenceFile(school_id=ctx["sid"], incident_id=incident_id, case_id=case_id, filename=name,
                        stored_name=stored, content_type=file.content_type or "application/octet-stream",
                        size_bytes=len(raw), uploaded_by=ctx["uid"])
    s.add(item); s.flush(); m.log(s, ctx, "create", "evidence", item.id); s.commit()
    return {"id": item.id, "filename": name, "size_bytes": len(raw)}


@router.get("/evidence")
def list_evidence(incident_id: int | None = None, case_id: int | None = None,
                  s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    q = select(EvidenceFile).where(EvidenceFile.school_id == ctx["sid"])
    if incident_id:
        q = q.where(EvidenceFile.incident_id == incident_id)
    if case_id:
        q = q.where(EvidenceFile.case_id == case_id)
    rows = s.scalars(q.order_by(EvidenceFile.id.desc())).all()
    return [{"id": x.id, "filename": x.filename, "incident_id": x.incident_id, "case_id": x.case_id,
             "size_bytes": x.size_bytes, "content_type": x.content_type,
             "created_at": x.created_at.isoformat()} for x in rows]


# --- Letter templates -------------------------------------------------------
@router.get("/letter-templates")
def list_templates(s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    rows = s.scalars(select(LetterTemplate).where(LetterTemplate.school_id == ctx["sid"])).all()
    return [{"id": x.id, "code": x.code, "name": x.name} for x in rows]


@router.post("/letter-templates", status_code=201)
def add_template(data: TemplateIn, s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal"))):
    if s.scalar(select(LetterTemplate).where(LetterTemplate.school_id == ctx["sid"], LetterTemplate.code == data.code)):
        raise HTTPException(409, "Template code exists")
    item = LetterTemplate(school_id=ctx["sid"], **data.model_dump())
    s.add(item); s.flush(); m.log(s, ctx, "create", "letter_template", item.id); s.commit()
    return {"id": item.id}


@router.post("/letter-templates/{template_id}/render")
def render_template(template_id: int, learner_id: int, s: Session = Depends(m.db),
                    ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    tpl = s.scalar(select(LetterTemplate).where(LetterTemplate.id == template_id, LetterTemplate.school_id == ctx["sid"]))
    learner = s.scalar(select(m.Learner).where(m.Learner.id == learner_id, m.Learner.school_id == ctx["sid"]))
    if not tpl or not learner:
        raise HTTPException(404, "Template or learner not found")
    text = (tpl.body
            .replace("{{learner_name}}", f"{learner.first_name} {learner.surname}")
            .replace("{{grade}}", learner.grade)
            .replace("{{class_name}}", learner.class_name)
            .replace("{{school}}", ctx["school"])
            .replace("{{date}}", datetime.now(timezone.utc).date().isoformat()))
    return {"code": tpl.code, "name": tpl.name, "rendered_text": text, "format": "plain-text-draft"}


# --- Parent portal ----------------------------------------------------------
@router.post("/parent-portal/invite", status_code=201)
def parent_invite(data: ParentInviteIn, s: Session = Depends(m.db),
                  ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    learner = s.scalar(select(m.Learner).where(m.Learner.id == data.learner_id, m.Learner.school_id == ctx["sid"]))
    if not learner:
        raise HTTPException(404, "Learner not found")
    token = secrets.token_urlsafe(32)
    item = ParentAccess(school_id=ctx["sid"], learner_id=data.learner_id, email=data.email.lower(),
                        token_hash=hashlib.sha256(token.encode()).hexdigest(),
                        expires_at=datetime.now(timezone.utc) + timedelta(days=7))
    s.add(item); s.flush()
    link = mailer.public_url(f"/#parent={token}")
    emailed = False
    if mailer.smtp_ready():
        try:
            mailer.send_email(data.email.lower(), data.subject,
                              f"You have been invited to acknowledge a SchoolCare notice for {learner.first_name}.\n\n"
                              f"Open this private link (expires in 7 days):\n{link}\n")
            emailed = True
        except Exception:
            raise HTTPException(503, "Parent invite email delivery failed")
    m.log(s, ctx, "invite", "parent_access", item.id); s.commit()
    out = {"id": item.id, "emailed": emailed, "expires_in_hours": 168}
    if not emailed:
        out["token"] = token
        out["notice"] = "SMTP not configured; share this token privately."
    return out


@router.post("/parent-portal/acknowledge")
def parent_ack(data: ParentAckIn, s: Session = Depends(m.db)):
    digest = hashlib.sha256(data.token.encode()).hexdigest()
    access = s.scalar(select(ParentAccess).where(ParentAccess.token_hash == digest))
    if not access or access.used or access.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(400, "Parent access token invalid or expired")
    access.used = True
    ack = ParentAck(school_id=access.school_id, learner_id=access.learner_id, subject=data.subject, email=access.email)
    s.add(ack); s.commit()
    return {"ok": True, "acknowledged": True}


@router.get("/parent-acknowledgements")
def list_acks(s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    rows = s.scalars(select(ParentAck).where(ParentAck.school_id == ctx["sid"]).order_by(ParentAck.id.desc()).limit(200)).all()
    return [{"id": x.id, "learner_id": x.learner_id, "subject": x.subject, "email": x.email,
             "acknowledged_at": x.acknowledged_at.isoformat()} for x in rows]


# --- Billing stubs ----------------------------------------------------------
@router.get("/billing/invoices")
def list_invoices(s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal"))):
    rows = s.scalars(select(Invoice).where(Invoice.school_id == ctx["sid"]).order_by(Invoice.id.desc())).all()
    return [{"id": x.id, "amount_cents": x.amount_cents, "currency": x.currency, "status": x.status,
             "description": x.description, "created_at": x.created_at.isoformat(),
             "gateway": "not_connected"} for x in rows]


@router.post("/billing/invoices", status_code=201)
def create_invoice(data: InvoiceIn, s: Session = Depends(m.db), ctx=Depends(m.require("school_admin"))):
    item = Invoice(school_id=ctx["sid"], amount_cents=data.amount_cents, description=data.description, status="issued")
    s.add(item); s.flush(); m.log(s, ctx, "create", "invoice", item.id); s.commit()
    return {"id": item.id, "status": item.status, "message": "Invoice recorded locally; no payment gateway is connected"}


@router.post("/billing/invoices/{invoice_id}/mark-paid")
def mark_paid(invoice_id: int, s: Session = Depends(m.db), ctx=Depends(m.current)):
    # School administrators cannot grant themselves paid subscription status.
    # Reconciliation by a separate platform operator is required.
    platform_user(s, ctx)
    item = s.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Invoice not found")
    if item.status != "issued":
        raise HTTPException(409, "Invoice already reconciled or closed")
    item.status = "paid_manual"
    # Manual invoice bookkeeping does NOT activate a subscription.
    m.log(s, ctx, "manual_reconcile", "invoice", item.id); s.commit()
    return {"id": item.id, "status": item.status, "subscription_activated": False}


# --- Retention / POPIA placeholders ----------------------------------------
@router.get("/privacy/retention")
def get_retention(s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal"))):
    rows = s.scalars(select(RetentionPolicy).where(RetentionPolicy.school_id == ctx["sid"])).all()
    return {"policies": [{"record_type": x.record_type, "retain_days": x.retain_days, "notes": x.notes} for x in rows],
            "disclaimer": "Configure with qualified legal advice. Defaults are placeholders only."}


@router.put("/privacy/retention")
def put_retention(data: RetentionIn, s: Session = Depends(m.db), ctx=Depends(m.require("school_admin"))):
    item = s.scalar(select(RetentionPolicy).where(RetentionPolicy.school_id == ctx["sid"],
                                                  RetentionPolicy.record_type == data.record_type))
    if not item:
        item = RetentionPolicy(school_id=ctx["sid"], record_type=data.record_type)
        s.add(item)
    item.retain_days = data.retain_days
    item.notes = data.notes
    s.commit()
    return {"ok": True}


@router.get("/privacy/status")
def privacy_status(ctx=Depends(m.require("school_admin", "principal"))):
    return {
        "popia_assessment_complete": False,
        "lawful_basis_recorded": False,
        "operator_agreement_on_file": False,
        "data_subject_request_process": "manual_placeholder",
        "message": "Legal and safeguarding assessments are required before processing identifiable children's data."
    }


# --- Platform admin ---------------------------------------------------------
@router.get("/platform/schools")
def platform_schools(s: Session = Depends(m.db), ctx=Depends(m.current)):
    platform_user(s, ctx)
    rows = s.scalars(select(m.School).order_by(m.School.id)).all()
    return [{"id": x.id, "name": x.name, "slug": x.slug, "plan": x.plan, "status": x.status} for x in rows]


@router.patch("/platform/schools")
def platform_patch_school(data: SchoolStatusIn, s: Session = Depends(m.db), ctx=Depends(m.current)):
    platform_user(s, ctx)
    school = s.get(m.School, data.school_id)
    if not school:
        raise HTTPException(404, "School not found")
    if data.status not in {"active", "suspended", "trial"}:
        raise HTTPException(400, "Invalid status")
    school.status = data.status
    if data.plan:
        school.plan = data.plan
    s.commit()
    return {"id": school.id, "status": school.status, "plan": school.plan}


@router.get("/platform/health")
def platform_health(s: Session = Depends(m.db), ctx=Depends(m.current)):
    platform_user(s, ctx)
    return {
        "schools": s.scalar(select(func.count()).select_from(m.School)),
        "users": s.scalar(select(func.count()).select_from(m.User)),
        "smtp_configured": mailer.smtp_ready(),
        "cookie_secure": os.getenv("COOKIE_SECURE", "false") == "true",
        "schema_auto_create": os.getenv("SCHEMA_AUTO_CREATE", "true").lower() == "true",
        "upload_root": str(UPLOAD_ROOT),
    }
