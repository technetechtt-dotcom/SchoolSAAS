"""v0.6 pilot foundation: MFA, CoC versions, hearings, evidence, parent links, platform admin, billing stubs."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib, os, secrets
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Response, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import String, ForeignKey, DateTime, Boolean, Text, Integer, UniqueConstraint, select, func
from sqlalchemy.orm import Session, Mapped, mapped_column
from app import main as m
from app import mailer
from app import mfa_crypto

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
    participants: Mapped[str] = mapped_column(Text, default="")
    attendance_notes: Mapped[str] = mapped_column(Text, default="")
    procedural_checks: Mapped[str] = mapped_column(Text, default="")


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
    subject: Mapped[str] = mapped_column(String(200), default="SchoolCare notice")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    delivery_status: Mapped[str] = mapped_column(String(40), default="pending")  # pending|emailed|manual|failed
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivery_notes: Mapped[str] = mapped_column(Text, default="")
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    gateway: Mapped[str] = mapped_column(String(40), default="none")
    payment_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class EvidenceAccessLog(m.Base):
    __tablename__ = "evidence_access_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence_files.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(40), default="download")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ParentDispute(m.Base):
    __tablename__ = "parent_disputes"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    access_id: Mapped[int | None] = mapped_column(ForeignKey("parent_access_tokens.id"), nullable=True)
    email: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open")
    resolution_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentEvent(m.Base):
    __tablename__ = "payment_events"
    __table_args__ = (UniqueConstraint("provider", "external_ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    event_type: Mapped[str] = mapped_column(String(60))
    external_ref: Mapped[str] = mapped_column(String(120))
    payload: Mapped[str] = mapped_column(Text, default="")
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


def billing_gateway_status() -> dict:
    provider = (os.getenv("BILLING_GATEWAY") or "none").strip().lower()
    secret = (os.getenv("BILLING_WEBHOOK_SECRET") or "").strip()
    connected = provider == "sandbox" and bool(secret)
    production_ready = provider not in {"", "none", "sandbox"} and bool(secret)
    return {
        "provider": provider if provider != "none" else None,
        "connected": connected,
        "production_payments_enabled": False,  # live provider not connected in this build
        "message": (
            "Sandbox only — production card processing remains disabled until a verified provider is connected."
            if connected else
            "Payment processing disabled. Set BILLING_GATEWAY=sandbox and BILLING_WEBHOOK_SECRET for sandbox tests only."
            if not production_ready else
            "Unknown provider configured; live settlement is still disabled in this build."
        ),
    }


def _parent_access_from_token(s: Session, token: str) -> ParentAccess:
    digest = hashlib.sha256(token.encode()).hexdigest()
    access = s.scalar(select(ParentAccess).where(ParentAccess.token_hash == digest))
    if not access or access.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(400, "Parent access token invalid or expired")
    return access


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
    participants: str = Field(default="", max_length=4000)


class HearingPatch(BaseModel):
    status: str = Field(min_length=2, max_length=40)
    outcome: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=4000)
    participants: str = Field(default="", max_length=4000)
    attendance_notes: str = Field(default="", max_length=4000)
    procedural_checks: str = Field(default="", max_length=4000)


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


class ParentDisputeIn(BaseModel):
    token: str
    reason: str = Field(min_length=5, max_length=4000)


class DisputeResolveIn(BaseModel):
    status: str = Field(min_length=2, max_length=30)
    resolution_notes: str = Field(default="", max_length=4000)


class InvoiceIn(BaseModel):
    amount_cents: int = Field(ge=100)
    description: str = Field(default="SchoolCare subscription", max_length=200)


class SandboxWebhookIn(BaseModel):
    invoice_id: int
    event: str = Field(default="payment.succeeded", max_length=60)
    external_ref: str = Field(min_length=4, max_length=120)
    school_id: int | None = None


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
    if user.mfa_enabled:
        raise HTTPException(409, "Disable the existing authenticator with its current code before replacing it")
    secret = pyotp.random_base32()
    user.mfa_secret = mfa_crypto.encrypt_secret(secret)
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
    if not pyotp.TOTP(mfa_crypto.decrypt_secret(user.mfa_secret)).verify(data.code, valid_window=1):
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
    if not pyotp.TOTP(mfa_crypto.decrypt_secret(user.mfa_secret)).verify(data.code, valid_window=1):
        raise HTTPException(401, "Invalid MFA code")
    user.mfa_enabled = False
    user.mfa_secret = None
    s.commit()
    return {"ok": True, "mfa_enabled": False}


@router.post("/mfa/verify-login")
def mfa_verify_login(data: MfaLogin, response: Response, request: Request, s: Session = Depends(m.db)):
    _require_pyotp()
    uid, sid = decode_mfa_pending(data.mfa_token)
    user = s.get(m.User, uid)
    if not user or not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(400, "MFA not enabled")
    if not pyotp.TOTP(mfa_crypto.decrypt_secret(user.mfa_secret)).verify(data.code, valid_window=1):
        raise HTTPException(401, "Invalid MFA code")
    mem = s.scalar(select(m.Membership).where(m.Membership.user_id == uid, m.Membership.school_id == sid))
    school = s.get(m.School, sid)
    if not mem or not mem.active or not school:
        raise HTTPException(403, "School access denied")
    token = m.issue_token(uid, sid, s, request)
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
def _hearing_out(x: Hearing):
    return {
        "id": x.id, "case_id": x.case_id, "scheduled_at": x.scheduled_at.isoformat(), "chair": x.chair,
        "status": x.status, "outcome": x.outcome, "notes": x.notes or "",
        "participants": getattr(x, "participants", "") or "",
        "attendance_notes": getattr(x, "attendance_notes", "") or "",
        "procedural_checks": getattr(x, "procedural_checks", "") or "",
    }


@router.get("/hearings")
def list_hearings(s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    rows = s.scalars(select(Hearing).where(Hearing.school_id == ctx["sid"]).order_by(Hearing.scheduled_at.desc())).all()
    return [_hearing_out(x) for x in rows]


@router.get("/hearings/{hearing_id}")
def get_hearing(hearing_id: int, s: Session = Depends(m.db),
                ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    item = s.scalar(select(Hearing).where(Hearing.id == hearing_id, Hearing.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Hearing not found")
    return _hearing_out(item)


@router.post("/hearings", status_code=201)
def add_hearing(data: HearingIn, s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal", "smt"))):
    case = s.scalar(select(m.Case).where(m.Case.id == data.case_id, m.Case.school_id == ctx["sid"]))
    if not case:
        raise HTTPException(404, "Case not found")
    try:
        when = datetime.fromisoformat(data.scheduled_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "scheduled_at must be ISO datetime")
    item = Hearing(school_id=ctx["sid"], case_id=data.case_id, scheduled_at=when, chair=data.chair,
                   notes=data.notes, participants=data.participants.strip())
    s.add(item); s.flush(); m.log(s, ctx, "create", "hearing", item.id); s.commit()
    return {"id": item.id}


@router.patch("/hearings/{hearing_id}")
def patch_hearing(hearing_id: int, data: HearingPatch, s: Session = Depends(m.db),
                  ctx=Depends(m.require("school_admin", "principal", "smt"))):
    item = s.scalar(select(Hearing).where(Hearing.id == hearing_id, Hearing.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Hearing not found")
    valid_statuses={"scheduled","in_progress","adjourned","completed","cancelled"}
    if data.status not in valid_statuses:
        raise HTTPException(400,"Invalid hearing status")
    if item.status in ("completed","cancelled") and data.status!=item.status:
        raise HTTPException(409,"Concluded hearing cannot be reopened without a formal review")
    if data.participants.strip():
        item.participants = data.participants.strip()
    if data.attendance_notes.strip():
        item.attendance_notes = data.attendance_notes.strip()
    if data.procedural_checks.strip():
        item.procedural_checks = data.procedural_checks.strip()
    if data.status=="completed":
        if not data.outcome.strip() and not (item.outcome or "").strip():
            raise HTTPException(422,"A documented human-reviewed outcome is required")
        attendance = (data.attendance_notes or item.attendance_notes or "").strip()
        participants = (data.participants or item.participants or "").strip()
        checks = (data.procedural_checks or item.procedural_checks or "").strip()
        if not attendance or not participants:
            raise HTTPException(422,"Attendance notes and participants are required before completing a hearing")
        if not checks:
            raise HTTPException(422,"Record procedural checks before completing a hearing")
    previous=item.status
    item.status = data.status
    if data.outcome:
        item.outcome = data.outcome
    if data.notes:
        item.notes = data.notes
    if previous!=data.status or data.outcome.strip():
        from app.operations import CaseEvent
        s.add(CaseEvent(school_id=ctx["sid"],case_id=item.case_id,
            author_user_id=ctx["uid"],kind="decision",
            note="Hearing status: "+previous+" → "+data.status+
                 (". Outcome recorded by authorised staff." if data.outcome.strip() else "")))
    m.log(s, ctx, "update", "hearing", item.id); s.commit()
    return _hearing_out(item)


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


def _evidence_for_viewer(s: Session, evidence_id: int, ctx: dict) -> EvidenceFile:
    item = s.scalar(select(EvidenceFile).where(EvidenceFile.id == evidence_id, EvidenceFile.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Evidence not found")
    if ctx["role"] == "educator":
        if not item.incident_id:
            raise HTTPException(403, "Educators may only access evidence on their own incidents")
        incident = s.scalar(select(m.Incident).where(
            m.Incident.id == item.incident_id, m.Incident.school_id == ctx["sid"],
            m.Incident.reporter_id == ctx["uid"]))
        if not incident:
            raise HTTPException(403, "Not authorised to access this evidence")
    return item


@router.get("/evidence/{evidence_id}/download")
def download_evidence(evidence_id: int, disposition: str = "attachment",
                      s: Session = Depends(m.db),
                      ctx=Depends(m.require("school_admin", "principal", "smt", "hod", "educator"))):
    item = _evidence_for_viewer(s, evidence_id, ctx)
    path = UPLOAD_ROOT / str(item.school_id) / item.stored_name
    if not path.is_file():
        raise HTTPException(404, "Evidence file missing from storage")
    action = "view" if disposition == "inline" else "download"
    s.add(EvidenceAccessLog(school_id=ctx["sid"], evidence_id=item.id, user_id=ctx["uid"], action=action))
    m.log(s, ctx, action, "evidence", item.id)
    s.commit()
    from fastapi.responses import FileResponse
    headers = {"Content-Disposition": f'{disposition}; filename="{item.filename}"'}
    return FileResponse(path, media_type=item.content_type or "application/octet-stream", headers=headers)


@router.get("/evidence/{evidence_id}/access-log")
def evidence_access_log(evidence_id: int, s: Session = Depends(m.db),
                        ctx=Depends(m.require("school_admin", "principal", "smt"))):
    item = s.scalar(select(EvidenceFile).where(EvidenceFile.id == evidence_id, EvidenceFile.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Evidence not found")
    rows = s.scalars(select(EvidenceAccessLog).where(
        EvidenceAccessLog.school_id == ctx["sid"], EvidenceAccessLog.evidence_id == evidence_id
    ).order_by(EvidenceAccessLog.id.desc()).limit(100)).all()
    return [{"id": x.id, "user_id": x.user_id, "action": x.action, "created_at": x.created_at.isoformat()} for x in rows]


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
def _deliver_parent_invite(item: ParentAccess, learner: m.Learner, token: str, subject: str) -> tuple[bool, str]:
    """Attempt SMTP delivery; returns (emailed, notes). Updates delivery counters on item."""
    link = mailer.public_url(f"/#parent={token}")
    item.delivery_attempts = int(item.delivery_attempts or 0) + 1
    item.last_delivery_at = datetime.now(timezone.utc)
    if mailer.smtp_ready():
        try:
            mailer.send_email(item.email, subject,
                              f"You have been invited to acknowledge a SchoolCare notice for {learner.first_name}.\n\n"
                              f"Open this private link (expires in 7 days):\n{link}\n")
            item.delivery_status = "emailed"
            item.delivery_notes = "Invitation emailed via SMTP"
            return True, item.delivery_notes
        except Exception as exc:
            item.delivery_status = "failed"
            item.delivery_notes = f"SMTP delivery failed: {exc}"
            return False, item.delivery_notes
    item.delivery_status = "manual"
    item.delivery_notes = "SMTP not configured; share private link/token with the guardian only"
    return False, item.delivery_notes


@router.post("/parent-portal/invite", status_code=201)
def parent_invite(data: ParentInviteIn, s: Session = Depends(m.db),
                  ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    learner = s.scalar(select(m.Learner).where(m.Learner.id == data.learner_id, m.Learner.school_id == ctx["sid"]))
    if not learner:
        raise HTTPException(404, "Learner not found")
    subject = data.subject.strip() or "SchoolCare notice"
    token = secrets.token_urlsafe(32)
    item = ParentAccess(school_id=ctx["sid"], learner_id=data.learner_id, email=data.email.lower(),
                        subject=subject, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                        created_at=datetime.now(timezone.utc), delivery_status="pending",
                        delivery_attempts=0, delivery_notes="")
    s.add(item); s.flush()
    emailed, notes = _deliver_parent_invite(item, learner, token, subject)
    if item.delivery_status == "failed":
        m.log(s, ctx, "invite_failed", "parent_access", item.id); s.commit()
        raise HTTPException(503, "Parent invite email delivery failed")
    m.log(s, ctx, "invite", "parent_access", item.id); s.commit()
    out = {"id": item.id, "emailed": emailed, "expires_in_hours": 168, "subject": subject,
           "delivery_status": item.delivery_status, "delivery_attempts": item.delivery_attempts,
           "delivery_notes": notes}
    if not emailed:
        out["token"] = token
        out["notice"] = notes
    else:
        out["notice"] = "Parent invitation emailed."
    return out


@router.post("/parent-portal/notices/{notice_id}/resend")
def parent_notice_resend(notice_id: int, s: Session = Depends(m.db),
                         ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    item = s.scalar(select(ParentAccess).where(ParentAccess.id == notice_id, ParentAccess.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Notice not found")
    if item.used:
        raise HTTPException(409, "Notice already acknowledged")
    exp = item.expires_at.replace(tzinfo=timezone.utc) if item.expires_at.tzinfo is None else item.expires_at
    if exp <= datetime.now(timezone.utc):
        raise HTTPException(409, "Notice expired — issue a new invite")
    learner = s.get(m.Learner, item.learner_id)
    if not learner:
        raise HTTPException(404, "Learner not found")
    # Issue a fresh token for resend so prior leaked tokens are superseded
    token = secrets.token_urlsafe(32)
    item.token_hash = hashlib.sha256(token.encode()).hexdigest()
    emailed, notes = _deliver_parent_invite(item, learner, token, item.subject)
    if item.delivery_status == "failed":
        m.log(s, ctx, "resend_failed", "parent_access", item.id); s.commit()
        raise HTTPException(503, "Parent notice resend failed")
    m.log(s, ctx, "resend", "parent_access", item.id); s.commit()
    out = {"id": item.id, "emailed": emailed, "delivery_status": item.delivery_status,
           "delivery_attempts": item.delivery_attempts, "delivery_notes": notes, "notice": notes}
    if not emailed:
        out["token"] = token
    return out


@router.get("/parent-portal/notice")
def parent_notice(token: str, s: Session = Depends(m.db)):
    """Public lookup so acknowledgement UI binds to the issued subject (not a forgeable default)."""
    access = _parent_access_from_token(s, token)
    if access.used:
        raise HTTPException(400, "This notice has already been acknowledged")
    learner = s.get(m.Learner, access.learner_id)
    school = s.get(m.School, access.school_id)
    return {
        "subject": access.subject,
        "learner_name": f"{learner.first_name} {learner.surname}" if learner else "",
        "school_name": school.name if school else "",
        "email": access.email,
        "expires_at": access.expires_at.isoformat(),
        "can_dispute": True,
    }


@router.post("/parent-portal/acknowledge")
def parent_ack(data: ParentAckIn, s: Session = Depends(m.db)):
    access = _parent_access_from_token(s, data.token)
    if access.used:
        raise HTTPException(400, "Parent access token invalid or expired")
    if data.subject.strip() != access.subject.strip():
        raise HTTPException(400, "Acknowledgement subject must match the issued school notice")
    access.used = True
    ack = ParentAck(school_id=access.school_id, learner_id=access.learner_id, subject=access.subject, email=access.email)
    s.add(ack); s.commit()
    return {"ok": True, "acknowledged": True}


@router.post("/parent-portal/dispute", status_code=201)
def parent_dispute(data: ParentDisputeIn, s: Session = Depends(m.db)):
    access = _parent_access_from_token(s, data.token)
    existing = s.scalar(select(ParentDispute).where(
        ParentDispute.school_id == access.school_id, ParentDispute.access_id == access.id,
        ParentDispute.status == "open"))
    if existing:
        raise HTTPException(409, "An open dispute already exists for this notice")
    item = ParentDispute(
        school_id=access.school_id, learner_id=access.learner_id, access_id=access.id,
        email=access.email, subject=access.subject, reason=data.reason.strip(), status="open")
    s.add(item); s.flush(); s.commit()
    return {"id": item.id, "status": item.status}


@router.get("/parent-portal/notices")
def list_parent_notices(s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    now = datetime.now(timezone.utc)
    rows = s.scalars(select(ParentAccess).where(ParentAccess.school_id == ctx["sid"])
                     .order_by(ParentAccess.id.desc()).limit(200)).all()
    out = []
    for x in rows:
        exp = x.expires_at.replace(tzinfo=timezone.utc) if x.expires_at.tzinfo is None else x.expires_at
        if x.used:
            status = "acknowledged"
        elif exp <= now:
            status = "expired"
        else:
            status = "pending"
        created = getattr(x, "created_at", None) or (x.expires_at - timedelta(days=7))
        delivery = getattr(x, "delivery_status", None) or ("email" if mailer.smtp_ready() else "manual")
        out.append({
            "id": x.id, "learner_id": x.learner_id, "email": x.email, "subject": x.subject,
            "status": status, "delivery": delivery,
            "delivery_attempts": int(getattr(x, "delivery_attempts", 0) or 0),
            "delivery_notes": getattr(x, "delivery_notes", "") or "",
            "last_delivery_at": x.last_delivery_at.isoformat() if getattr(x, "last_delivery_at", None) else None,
            "expires_at": x.expires_at.isoformat(),
            "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created),
            "can_resend": status == "pending",
        })
    return out


@router.get("/parent-portal/disputes")
def list_disputes(s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    rows = s.scalars(select(ParentDispute).where(ParentDispute.school_id == ctx["sid"])
                     .order_by(ParentDispute.id.desc()).limit(200)).all()
    return [{"id": x.id, "learner_id": x.learner_id, "email": x.email, "subject": x.subject,
             "reason": x.reason, "status": x.status, "resolution_notes": x.resolution_notes,
             "created_at": x.created_at.isoformat(),
             "resolved_at": x.resolved_at.isoformat() if x.resolved_at else None} for x in rows]


@router.patch("/parent-portal/disputes/{dispute_id}")
def resolve_dispute(dispute_id: int, data: DisputeResolveIn, s: Session = Depends(m.db),
                    ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    item = s.scalar(select(ParentDispute).where(ParentDispute.id == dispute_id, ParentDispute.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Dispute not found")
    if data.status not in {"resolved", "upheld", "rejected"}:
        raise HTTPException(400, "Invalid dispute resolution status")
    item.status = data.status
    item.resolution_notes = data.resolution_notes.strip()
    item.resolved_at = datetime.now(timezone.utc)
    m.log(s, ctx, "resolve", "parent_dispute", item.id); s.commit()
    return {"id": item.id, "status": item.status}


@router.get("/parent-acknowledgements")
def list_acks(s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    rows = s.scalars(select(ParentAck).where(ParentAck.school_id == ctx["sid"]).order_by(ParentAck.id.desc()).limit(200)).all()
    return [{"id": x.id, "learner_id": x.learner_id, "subject": x.subject, "email": x.email,
             "acknowledged_at": x.acknowledged_at.isoformat()} for x in rows]


# --- Billing ----------------------------------------------------------------
@router.get("/billing/gateway")
def billing_gateway(ctx=Depends(m.require("school_admin", "principal"))):
    return billing_gateway_status()


@router.get("/billing/invoices")
def list_invoices(s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal"))):
    gw = billing_gateway_status()
    rows = s.scalars(select(Invoice).where(Invoice.school_id == ctx["sid"]).order_by(Invoice.id.desc())).all()
    return [{"id": x.id, "amount_cents": x.amount_cents, "currency": x.currency, "status": x.status,
             "description": x.description, "created_at": x.created_at.isoformat(),
             "gateway": getattr(x, "gateway", None) or ("sandbox" if gw["connected"] else "not_connected"),
             "payment_ref": getattr(x, "payment_ref", None),
             "paid_at": x.paid_at.isoformat() if getattr(x, "paid_at", None) else None} for x in rows]


@router.post("/billing/invoices", status_code=201)
def create_invoice(data: InvoiceIn, s: Session = Depends(m.db), ctx=Depends(m.require("school_admin"))):
    gw = billing_gateway_status()
    item = Invoice(school_id=ctx["sid"], amount_cents=data.amount_cents, description=data.description,
                   status="issued", gateway="sandbox" if gw["connected"] else "none")
    s.add(item); s.flush(); m.log(s, ctx, "create", "invoice", item.id); s.commit()
    msg = ("Invoice issued. Start checkout to obtain a payment reference; confirmation requires a signed webhook."
           if gw["connected"] else
           "Invoice recorded locally; connect BILLING_GATEWAY=sandbox to enable payment confirmation.")
    return {"id": item.id, "status": item.status, "gateway": item.gateway, "message": msg}


@router.post("/billing/invoices/{invoice_id}/checkout")
def start_checkout(invoice_id: int, s: Session = Depends(m.db), ctx=Depends(m.require("school_admin", "principal"))):
    gw = billing_gateway_status()
    if not gw["connected"]:
        raise HTTPException(503, "Payment gateway is not connected")
    item = s.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Invoice not found")
    if item.status not in {"issued", "awaiting_payment"}:
        raise HTTPException(409, "Invoice is not open for checkout")
    ref = item.payment_ref or f"sandbox_{item.id}_{secrets.token_hex(6)}"
    item.payment_ref = ref
    item.gateway = "sandbox"
    item.status = "awaiting_payment"
    m.log(s, ctx, "checkout", "invoice", item.id); s.commit()
    return {
        "id": item.id, "status": item.status, "payment_ref": ref, "provider": "sandbox",
        "message": "Checkout created. Payment is confirmed only by signed sandbox webhook — not by staff claim.",
    }


@router.post("/billing/webhooks/sandbox")
def sandbox_webhook(data: SandboxWebhookIn, s: Session = Depends(m.db),
                    x_billing_webhook_secret: str | None = Header(default=None),
                    ctx=Depends(m.current)):
    """Confirm sandbox payment only with matching checkout reference. Never processes live card payments."""
    gw = billing_gateway_status()
    if not gw["connected"]:
        raise HTTPException(503, "Sandbox gateway is not configured — production payment processing is disabled")
    if (os.getenv("BILLING_GATEWAY") or "").strip().lower() not in {"sandbox"}:
        raise HTTPException(503, "Only the sandbox gateway is enabled in this build")
    secret = (os.getenv("BILLING_WEBHOOK_SECRET") or "").strip()
    authorised = bool(secret and x_billing_webhook_secret and secrets.compare_digest(x_billing_webhook_secret, secret))
    if not authorised:
        try:
            platform_user(s, ctx)
            authorised = True
        except HTTPException:
            authorised = False
    if not authorised:
        raise HTTPException(403, "Sandbox webhook requires X-Billing-Webhook-Secret or platform administrator")
    if data.event != "payment.succeeded":
        raise HTTPException(400, "Unsupported sandbox event")
    q = select(Invoice).where(Invoice.id == data.invoice_id)
    if data.school_id is not None:
        q = q.where(Invoice.school_id == data.school_id)
    item = s.scalar(q)
    if not item:
        raise HTTPException(404, "Invoice not found")
    if item.status in {"paid", "paid_gateway", "paid_manual"}:
        return {"id": item.id, "status": item.status, "message": "Already reconciled", "subscription_activated": False}
    if item.status != "awaiting_payment" or not (item.payment_ref or "").strip():
        raise HTTPException(409, "Invoice must complete checkout and have a payment reference before settlement")
    if not secrets.compare_digest(data.external_ref, item.payment_ref):
        raise HTTPException(409, "Payment reference does not match the active checkout for this invoice")
    prior = s.scalar(select(PaymentEvent).where(
        PaymentEvent.provider == "sandbox", PaymentEvent.external_ref == data.external_ref))
    if prior:
        return {"id": item.id, "status": item.status, "message": "Duplicate payment event ignored",
                "subscription_activated": False}
    item.status = "paid_gateway"
    item.gateway = "sandbox"
    item.paid_at = datetime.now(timezone.utc)
    s.add(PaymentEvent(school_id=item.school_id, invoice_id=item.id, provider="sandbox",
                       event_type=data.event, external_ref=data.external_ref,
                       payload=f"invoice:{item.id}:school:{item.school_id}"))
    school = s.get(m.School, item.school_id)
    activated = False
    if school and (school.plan or "trial") in {"trial", "free", ""}:
        school.plan = "standard"
        school.status = "active"
        activated = True
    m.log(s, {"sid": item.school_id, "uid": ctx["uid"]}, "gateway_reconcile", "invoice", item.id)
    s.commit()
    return {"id": item.id, "status": item.status, "subscription_activated": activated,
            "message": "Payment confirmed via sandbox gateway event"}


@router.post("/billing/invoices/{invoice_id}/mark-paid")
def mark_paid(invoice_id: int, s: Session = Depends(m.db), ctx=Depends(m.current)):
    # School administrators cannot grant themselves paid subscription status.
    # Reconciliation by a separate platform operator is required.
    platform_user(s, ctx)
    # Platform operators may reconcile only within the active school workspace.
    item = s.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.school_id == ctx["sid"]))
    if not item:
        raise HTTPException(404, "Invoice not found in the active school workspace")
    if item.status not in {"issued", "awaiting_payment"}:
        raise HTTPException(409, "Invoice already reconciled or closed")
    item.status = "paid_manual"
    item.paid_at = datetime.now(timezone.utc)
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
