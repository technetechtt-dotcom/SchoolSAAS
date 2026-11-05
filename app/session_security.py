"""Staff invitation lifecycle and authenticated session self-management."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import hashlib, secrets, os
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import String, ForeignKey, DateTime, Boolean, Integer, select, delete
from sqlalchemy.orm import Mapped, mapped_column, Session
from app import main as m
from app import mailer

router = APIRouter(prefix="/api")
ADMIN = ("school_admin", "principal")


class SessionLabelIn(BaseModel):
    label: str = Field(default="", max_length=120)


def _ua_label(ua: str) -> str:
    ua = (ua or "").strip()
    if not ua:
        return "Unknown device"
    low = ua.lower()
    browser = "Browser"
    if "edg/" in low:
        browser = "Edge"
    elif "chrome/" in low and "chromium" not in low:
        browser = "Chrome"
    elif "firefox/" in low:
        browser = "Firefox"
    elif "safari/" in low and "chrome/" not in low:
        browser = "Safari"
    os_name = "device"
    if "windows" in low:
        os_name = "Windows"
    elif "android" in low:
        os_name = "Android"
    elif "iphone" in low or "ipad" in low:
        os_name = "iOS"
    elif "mac os" in low or "macintosh" in low:
        os_name = "macOS"
    elif "linux" in low:
        os_name = "Linux"
    return f"{browser} on {os_name}"


def enrich_session_on_issue(session_row: m.ActiveSession, request: Request | None = None, label: str = ""):
    """Best-effort metadata for newly issued sessions (columns may be absent on old DBs)."""
    now = datetime.now(timezone.utc)
    if hasattr(session_row, "created_at") and getattr(session_row, "created_at", None) is None:
        session_row.created_at = now
    if hasattr(session_row, "last_seen_at"):
        session_row.last_seen_at = now
    if hasattr(session_row, "user_agent") and request is not None:
        session_row.user_agent = (request.headers.get("user-agent") or "")[:240]
    if hasattr(session_row, "label"):
        session_row.label = (label or _ua_label(getattr(session_row, "user_agent", "") or "")).strip()[:120]


def touch_session(record: m.ActiveSession):
    if hasattr(record, "last_seen_at"):
        record.last_seen_at = datetime.now(timezone.utc)


def _current_jti(request: Request) -> str | None:
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        import jwt
        payload = jwt.decode(token, m.JWT_SECRET, algorithms=["HS256"])
        return payload.get("jti")
    except Exception:
        return None


@router.get("/sessions")
def list_sessions(request: Request, s: Session = Depends(m.db), ctx=Depends(m.current)):
    jti = _current_jti(request)
    current_hash = hashlib.sha256(jti.encode()).hexdigest() if jti else ""
    rows = s.scalars(select(m.ActiveSession).where(
        m.ActiveSession.user_id == ctx["uid"], m.ActiveSession.school_id == ctx["sid"])
        .order_by(m.ActiveSession.id.desc())).all()
    now = datetime.now(timezone.utc)
    out = []
    for x in rows:
        exp = x.expires_at.replace(tzinfo=timezone.utc) if x.expires_at.tzinfo is None else x.expires_at
        if exp <= now:
            continue
        out.append({
            "id": x.id,
            "current": x.token_hash == current_hash,
            "label": getattr(x, "label", None) or _ua_label(getattr(x, "user_agent", "") or ""),
            "user_agent": getattr(x, "user_agent", "") or "",
            "created_at": (getattr(x, "created_at", None) or x.expires_at - timedelta(hours=8)).isoformat(),
            "last_seen_at": (getattr(x, "last_seen_at", None) or getattr(x, "created_at", None) or x.expires_at).isoformat()
            if (getattr(x, "last_seen_at", None) or getattr(x, "created_at", None) or x.expires_at) else None,
            "expires_at": x.expires_at.isoformat(),
        })
    return {"items": out, "count": len(out),
            "notice": "Revoking a session signs that device out immediately. This is per-user session control, not network rate limiting."}


@router.post("/sessions/{session_id}/revoke")
def revoke_session(session_id: int, request: Request, s: Session = Depends(m.db), ctx=Depends(m.current)):
    row = s.scalar(select(m.ActiveSession).where(
        m.ActiveSession.id == session_id, m.ActiveSession.user_id == ctx["uid"],
        m.ActiveSession.school_id == ctx["sid"]))
    if not row:
        raise HTTPException(404, "Session not found")
    jti = _current_jti(request)
    if jti and row.token_hash == hashlib.sha256(jti.encode()).hexdigest():
        raise HTTPException(400, "Use Sign out to end the current session")
    s.delete(row)
    m.log(s, ctx, "revoke", "active_session", session_id)
    s.commit()
    return {"ok": True}


@router.post("/sessions/revoke-others")
def revoke_other_sessions(request: Request, s: Session = Depends(m.db), ctx=Depends(m.current)):
    jti = _current_jti(request)
    current_hash = hashlib.sha256(jti.encode()).hexdigest() if jti else ""
    rows = s.scalars(select(m.ActiveSession).where(
        m.ActiveSession.user_id == ctx["uid"], m.ActiveSession.school_id == ctx["sid"])).all()
    removed = 0
    for row in rows:
        if row.token_hash == current_hash:
            continue
        s.delete(row)
        removed += 1
    m.log(s, ctx, "revoke_others", "active_session", ctx["uid"])
    s.commit()
    return {"ok": True, "revoked": removed}


@router.get("/invitations")
def list_invitations(s: Session = Depends(m.db), ctx=Depends(m.require(*ADMIN))):
    rows = s.scalars(select(m.StaffInvite).where(m.StaffInvite.school_id == ctx["sid"])
                     .order_by(m.StaffInvite.id.desc()).limit(200)).all()
    now = datetime.now(timezone.utc)
    out = []
    for x in rows:
        exp = x.expires_at.replace(tzinfo=timezone.utc) if x.expires_at.tzinfo is None else x.expires_at
        revoked = bool(getattr(x, "revoked", False))
        if x.used:
            status = "accepted"
        elif revoked:
            status = "revoked"
        elif exp <= now:
            status = "expired"
        else:
            status = "pending"
        out.append({
            "id": x.id, "email": x.email, "role": x.role,
            "assigned_class": x.assigned_class or "",
            "status": status,
            "delivery_status": getattr(x, "delivery_status", "") or "",
            "delivery_attempts": int(getattr(x, "delivery_attempts", 0) or 0),
            "expires_at": x.expires_at.isoformat(),
            "created_at": (getattr(x, "created_at", None) or (x.expires_at - timedelta(days=3))).isoformat(),
            "can_resend": status == "pending",
            "can_revoke": status == "pending",
        })
    return out


def _deliver_staff_invite(invite: m.StaffInvite, token: str, school_name: str) -> tuple[bool, str]:
    invite.delivery_attempts = int(getattr(invite, "delivery_attempts", 0) or 0) + 1
    if hasattr(invite, "last_delivery_at"):
        invite.last_delivery_at = datetime.now(timezone.utc)
    if mailer.smtp_ready():
        try:
            mailer.send_email(invite.email, "SchoolCare staff invitation",
                              f"You have been invited to join {school_name} as {invite.role}.\n\n"
                              f"Accept in the app with this invitation token (expires in 72 hours):\n{token}\n\n"
                              f"Open: {mailer.public_url()}\n")
            if hasattr(invite, "delivery_status"):
                invite.delivery_status = "emailed"
            return True, "Invitation emailed"
        except Exception as exc:
            if hasattr(invite, "delivery_status"):
                invite.delivery_status = "failed"
            return False, f"SMTP delivery failed: {exc}"
    if hasattr(invite, "delivery_status"):
        invite.delivery_status = "manual"
    return False, "SMTP not configured; share this token privately"


@router.post("/invitations/{invite_id}/resend")
def resend_invitation(invite_id: int, s: Session = Depends(m.db), ctx=Depends(m.require(*ADMIN))):
    inv = s.scalar(select(m.StaffInvite).where(
        m.StaffInvite.id == invite_id, m.StaffInvite.school_id == ctx["sid"]))
    if not inv:
        raise HTTPException(404, "Invitation not found")
    if inv.used or bool(getattr(inv, "revoked", False)):
        raise HTTPException(409, "Invitation is no longer pending")
    exp = inv.expires_at.replace(tzinfo=timezone.utc) if inv.expires_at.tzinfo is None else inv.expires_at
    if exp <= datetime.now(timezone.utc):
        raise HTTPException(409, "Invitation expired — create a new invite")
    token = secrets.token_urlsafe(32)
    inv.token_hash = hashlib.sha256(token.encode()).hexdigest()
    emailed, notes = _deliver_staff_invite(inv, token, ctx["school"])
    if getattr(inv, "delivery_status", "") == "failed":
        m.log(s, ctx, "resend_failed", "staff_invite", inv.id); s.commit()
        raise HTTPException(503, "Invitation email delivery failed")
    m.log(s, ctx, "resend", "staff_invite", inv.id); s.commit()
    out = {"id": inv.id, "emailed": emailed, "notice": notes,
           "delivery_status": getattr(inv, "delivery_status", ""),
           "delivery_attempts": int(getattr(inv, "delivery_attempts", 0) or 0)}
    if not emailed:
        out["token"] = token
    return out


@router.post("/invitations/{invite_id}/revoke")
def revoke_invitation(invite_id: int, s: Session = Depends(m.db), ctx=Depends(m.require(*ADMIN))):
    inv = s.scalar(select(m.StaffInvite).where(
        m.StaffInvite.id == invite_id, m.StaffInvite.school_id == ctx["sid"]))
    if not inv:
        raise HTTPException(404, "Invitation not found")
    if inv.used:
        raise HTTPException(409, "Invitation already accepted")
    if hasattr(inv, "revoked"):
        inv.revoked = True
    else:
        # Fallback: expire immediately when column absent
        inv.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    # Rotate hash so prior tokens cannot be used
    inv.token_hash = hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest()
    m.log(s, ctx, "revoke", "staff_invite", inv.id); s.commit()
    return {"ok": True, "status": "revoked"}
