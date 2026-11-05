"""MFA recovery codes, security event feed, and guardian token inbox."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import hashlib, secrets, re
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import String, ForeignKey, DateTime, Boolean, Text, select, delete, func
from sqlalchemy.orm import Mapped, mapped_column, Session
from app import main as m
from app import mailer
from app import mfa_crypto
import os

router = APIRouter(prefix="/api")
ADMIN = ("school_admin", "principal")
RECOVERY_COUNT = 10


class MfaRecoveryCode(m.Base):
    __tablename__ = "mfa_recovery_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SecurityEvent(m.Base):
    __tablename__ = "security_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    emailed: Mapped[bool] = mapped_column(Boolean, default=False)


class MfaRecoveryLogin(BaseModel):
    mfa_token: str
    recovery_code: str = Field(min_length=8, max_length=40)


class MfaAdminResetIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class RegenerateCodesIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)


def _hash_code(code: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "", code).upper()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _generate_plain_codes(n: int = RECOVERY_COUNT) -> list[str]:
    codes = []
    for _ in range(n):
        raw = secrets.token_hex(4).upper()
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def replace_recovery_codes(s: Session, user_id: int) -> list[str]:
    s.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id))
    plain = _generate_plain_codes()
    for code in plain:
        s.add(MfaRecoveryCode(user_id=user_id, code_hash=_hash_code(code)))
    return plain


def record_security_event(s: Session, user_id: int, school_id: int | None, event_type: str,
                          detail: str = "", email_user: bool = False) -> SecurityEvent:
    evt = SecurityEvent(user_id=user_id, school_id=school_id, event_type=event_type,
                        detail=detail.strip()[:2000], emailed=False)
    s.add(evt)
    s.flush()
    if email_user:
        user = s.get(m.User, user_id)
        if user:
            from app.mail_outbox import send_or_queue
            body = (
                "A security-related change occurred on your SchoolCare account.\n\n"
                f"Event: {event_type}\n"
                f"Detail: {detail or 'n/a'}\n"
                f"When (UTC): {datetime.now(timezone.utc).isoformat()}\n\n"
                "If this was not you, reset your password and contact your school administrator.\n"
                f"{mailer.public_url()}\n")
            result = send_or_queue(
                s, user.email,
                f"SchoolCare security alert: {event_type.replace('_', ' ')}",
                body, school_id=school_id)
            evt.emailed = bool(result.get("sent"))
    return evt


def consume_recovery_code(s: Session, user_id: int, code: str) -> bool:
    digest = _hash_code(code)
    row = s.scalar(select(MfaRecoveryCode).where(
        MfaRecoveryCode.user_id == user_id, MfaRecoveryCode.code_hash == digest,
        MfaRecoveryCode.used_at.is_(None)))
    if not row:
        return False
    row.used_at = datetime.now(timezone.utc)
    return True


@router.get("/security/events")
def list_security_events(s: Session = Depends(m.db), ctx=Depends(m.current)):
    rows = s.scalars(select(SecurityEvent).where(SecurityEvent.user_id == ctx["uid"])
                     .order_by(SecurityEvent.id.desc()).limit(50)).all()
    return [{"id": x.id, "event_type": x.event_type, "detail": x.detail,
             "created_at": x.created_at.isoformat(), "emailed": x.emailed} for x in rows]


@router.get("/mfa/recovery-status")
def recovery_status(s: Session = Depends(m.db), ctx=Depends(m.current)):
    user = s.get(m.User, ctx["uid"])
    remaining = s.scalar(select(func.count()).select_from(MfaRecoveryCode).where(
        MfaRecoveryCode.user_id == ctx["uid"], MfaRecoveryCode.used_at.is_(None))) or 0
    return {"mfa_enabled": bool(user and user.mfa_enabled),
            "recovery_codes_remaining": int(remaining),
            "notice": "Store recovery codes offline. Each code works once if you lose your authenticator."}


@router.post("/mfa/recovery-codes/regenerate")
def regenerate_recovery_codes(data: RegenerateCodesIn, s: Session = Depends(m.db), ctx=Depends(m.current)):
    from app.pilot_pack import _require_pyotp
    import pyotp
    _require_pyotp()
    user = s.get(m.User, ctx["uid"])
    if not user or not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(400, "Enable MFA before generating recovery codes")
    if not pyotp.TOTP(mfa_crypto.decrypt_secret(user.mfa_secret)).verify(data.code, valid_window=1):
        raise HTTPException(401, "Invalid MFA code")
    codes = replace_recovery_codes(s, user.id)
    record_security_event(s, user.id, ctx["sid"], "mfa_recovery_regenerated",
                          "Recovery codes regenerated", email_user=True)
    m.log(s, ctx, "regenerate", "mfa_recovery", user.id)
    s.commit()
    return {"codes": codes, "count": len(codes),
            "notice": "Save these codes now. They will not be shown again."}


@router.post("/mfa/verify-recovery")
def mfa_verify_recovery(data: MfaRecoveryLogin, response: Response, request: Request,
                        s: Session = Depends(m.db)):
    from app.pilot_pack import decode_mfa_pending
    uid, sid = decode_mfa_pending(data.mfa_token)
    user = s.get(m.User, uid)
    if not user or not user.mfa_enabled:
        raise HTTPException(400, "MFA not enabled")
    if not consume_recovery_code(s, uid, data.recovery_code):
        raise HTTPException(401, "Invalid or already used recovery code")
    mem = s.scalar(select(m.Membership).where(m.Membership.user_id == uid, m.Membership.school_id == sid))
    school = s.get(m.School, sid)
    if not mem or not mem.active or not school:
        raise HTTPException(403, "School access denied")
    token = m.issue_token(uid, sid, s, request)
    remaining = s.scalar(select(func.count()).select_from(MfaRecoveryCode).where(
        MfaRecoveryCode.user_id == uid, MfaRecoveryCode.used_at.is_(None))) or 0
    record_security_event(s, uid, sid, "mfa_recovery_used",
                          f"Recovery code used; {remaining} remaining", email_user=True)
    s.commit()
    response.set_cookie("session", token, httponly=True,
                        secure=os.getenv("COOKIE_SECURE", "false") == "true",
                        samesite="lax", max_age=28800)
    return {"school": school.name, "role": mem.role, "mfa_ok": True,
            "recovery_codes_remaining": int(remaining),
            "notice": "You signed in with a recovery code. Regenerate codes after you restore authenticator access."}


@router.post("/members/{member_id}/mfa-reset")
def admin_mfa_reset(member_id: int, data: MfaAdminResetIn, s: Session = Depends(m.db),
                    ctx=Depends(m.require(*ADMIN))):
    membership = s.scalar(select(m.Membership).where(
        m.Membership.id == member_id, m.Membership.school_id == ctx["sid"]))
    if not membership:
        raise HTTPException(404, "Member not found")
    if membership.user_id == ctx["uid"]:
        raise HTTPException(400, "Disable your own MFA from Security settings")
    if membership.role == "school_admin" and ctx["role"] != "school_admin":
        raise HTTPException(403, "Only a school administrator can reset another administrator's MFA")
    user = s.get(m.User, membership.user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.mfa_enabled = False
    user.mfa_secret = None
    s.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    s.execute(delete(m.ActiveSession).where(m.ActiveSession.user_id == user.id))
    record_security_event(s, user.id, ctx["sid"], "mfa_admin_reset",
                          f"Reset by staff uid={ctx['uid']}: {data.reason}", email_user=True)
    m.log(s, ctx, "mfa_reset", "membership", membership.id)
    s.commit()
    return {"ok": True, "mfa_enabled": False,
            "notice": "MFA cleared and sessions revoked. The staff member must re-enrol MFA after signing in."}


@router.get("/parent-portal/inbox")
def parent_inbox(token: str, s: Session = Depends(m.db)):
    """Token-scoped guardian inbox: notices for the same email within the issuing school."""
    from app.pilot_pack import _parent_access_from_token, ParentAccess, ParentDispute, ParentAck
    access = _parent_access_from_token(s, token)
    learner = s.get(m.Learner, access.learner_id)
    school = s.get(m.School, access.school_id)
    now = datetime.now(timezone.utc)
    notices = s.scalars(select(ParentAccess).where(
        ParentAccess.school_id == access.school_id,
        ParentAccess.email == access.email)
        .order_by(ParentAccess.id.desc()).limit(50)).all()
    disputes = {d.access_id: d for d in s.scalars(select(ParentDispute).where(
        ParentDispute.school_id == access.school_id,
        ParentDispute.email == access.email)).all()}
    items = []
    for x in notices:
        exp = x.expires_at.replace(tzinfo=timezone.utc) if x.expires_at.tzinfo is None else x.expires_at
        if x.used:
            status = "acknowledged"
        elif exp <= now:
            status = "expired"
        else:
            status = "pending"
        disp = disputes.get(x.id)
        items.append({
            "id": x.id,
            "learner_id": x.learner_id,
            "subject": x.subject,
            "status": status,
            "is_current_token": x.id == access.id,
            "expires_at": x.expires_at.isoformat(),
            "dispute_status": disp.status if disp else None,
            "can_acknowledge": status == "pending" and x.id == access.id,
            "can_dispute": status == "pending" and x.id == access.id and not disp,
        })
    return {
        "school_name": school.name if school else "",
        "email": access.email,
        "learner_name": f"{learner.first_name} {learner.surname}" if learner else "",
        "current_subject": access.subject,
        "items": items,
        "notice": "This inbox is bound to the private invitation token. It is not a full guardian account.",
    }
