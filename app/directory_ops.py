"""Learner import preview/bulk updates and periodic staff access review."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, DateTime, Text, Integer, select, func, delete
from sqlalchemy.orm import Mapped, mapped_column, Session
from app import main as m

router = APIRouter(prefix="/api")
ADMIN = ("school_admin", "principal")


class StaffAccessReview(m.Base):
    __tablename__ = "staff_access_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    reviewed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str] = mapped_column(Text, default="")
    deactivated_count: Mapped[int] = mapped_column(Integer, default=0)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class BulkLearnerRow(BaseModel):
    admission_no: str = Field(default="", max_length=80)
    first_name: str = Field(default="", max_length=120)
    surname: str = Field(default="", max_length=120)
    grade: str = Field(default="", max_length=25)
    class_name: str = Field(default="", max_length=30)


class BulkLearnerPreviewIn(BaseModel):
    rows: list[BulkLearnerRow] = Field(min_length=1, max_length=1000)


class BulkUpdateRow(BaseModel):
    admission_no: str | None = Field(default=None, max_length=80)
    learner_id: int | None = None
    grade: str | None = Field(default=None, max_length=25)
    class_name: str | None = Field(default=None, max_length=30)
    active: bool | None = None
    first_name: str | None = Field(default=None, max_length=120)
    surname: str | None = Field(default=None, max_length=120)


class BulkUpdateIn(BaseModel):
    rows: list[BulkUpdateRow] = Field(min_length=1, max_length=1000)
    record_placements: bool = False
    placement_reason: str = Field(default="correction", max_length=40)


class AccessReviewCompleteIn(BaseModel):
    notes: str = Field(default="", max_length=2000)
    deactivate_member_ids: list[int] = Field(default_factory=list, max_length=200)


def _validate_import_rows(s: Session, sid: int, rows: list[BulkLearnerRow]) -> dict:
    existing = set(s.scalars(select(m.Learner.admission_no).where(m.Learner.school_id == sid)).all())
    seen_in_file: set[str] = set()
    valid = []
    issues = []
    will_create = 0
    for idx, row in enumerate(rows, 1):
        errors = []
        first = (row.first_name or "").strip()
        surname = (row.surname or "").strip()
        grade = (row.grade or "").strip()
        class_name = (row.class_name or "").strip()
        admission = (row.admission_no or "").strip()
        if not first:
            errors.append("first_name required")
        if not surname:
            errors.append("surname required")
        if not grade:
            errors.append("grade required")
        if not class_name:
            errors.append("class_name required")
        if admission:
            if admission in existing:
                errors.append("admission_no already exists at this school")
            if admission in seen_in_file:
                errors.append("admission_no duplicated in this file")
            seen_in_file.add(admission)
        if errors:
            issues.append({"row": idx, "admission_no": admission or None, "errors": errors,
                           "action": "reject"})
            continue
        action = "create"
        preview_admission = admission or "(auto-generated)"
        if not admission:
            # Reserve unique placeholder marker for count only
            pass
        will_create += 1
        valid.append({
            "row": idx, "admission_no": preview_admission, "first_name": first, "surname": surname,
            "grade": grade, "class_name": class_name, "action": action,
        })
    return {
        "submitted": len(rows),
        "valid": len(valid),
        "invalid": len(issues),
        "will_create": will_create,
        "issues": issues[:200],
        "sample_valid": valid[:20],
        "can_import": len(issues) == 0 or will_create > 0,
        "notice": "Preview only — no learners were written. Import to commit valid rows; invalid rows are skipped.",
    }


@router.post("/learners/import/preview")
def preview_learner_import(data: BulkLearnerPreviewIn, s: Session = Depends(m.db),
                           ctx=Depends(m.require(*ADMIN))):
    return _validate_import_rows(s, ctx["sid"], data.rows)


@router.post("/learners/bulk-update")
def bulk_update_learners(data: BulkUpdateIn, s: Session = Depends(m.db),
                         ctx=Depends(m.require(*ADMIN))):
    updated = 0
    skipped = []
    placement_reason = (data.placement_reason or "correction").strip() or "correction"
    if placement_reason not in {"promotion", "transfer", "withdrawal", "reenrolment", "correction"}:
        raise HTTPException(400, "Invalid placement_reason")
    for idx, row in enumerate(data.rows, 1):
        learner = None
        if row.learner_id is not None:
            learner = s.scalar(select(m.Learner).where(
                m.Learner.id == row.learner_id, m.Learner.school_id == ctx["sid"]))
        elif row.admission_no:
            learner = s.scalar(select(m.Learner).where(
                m.Learner.school_id == ctx["sid"], m.Learner.admission_no == row.admission_no.strip()))
        if not learner:
            skipped.append({"row": idx, "reason": "Learner not found",
                            "admission_no": row.admission_no, "learner_id": row.learner_id})
            continue
        old_grade, old_class = learner.grade, learner.class_name
        changed = False
        if row.grade is not None and row.grade.strip() and row.grade.strip() != learner.grade:
            learner.grade = row.grade.strip(); changed = True
        if row.class_name is not None and row.class_name.strip() and row.class_name.strip() != learner.class_name:
            learner.class_name = row.class_name.strip(); changed = True
        if row.first_name is not None and row.first_name.strip():
            learner.first_name = row.first_name.strip(); changed = True
        if row.surname is not None and row.surname.strip():
            learner.surname = row.surname.strip(); changed = True
        if row.active is not None and row.active != learner.active:
            learner.active = row.active; changed = True
        if not changed:
            skipped.append({"row": idx, "reason": "No changes", "admission_no": learner.admission_no})
            continue
        if data.record_placements and (learner.grade != old_grade or learner.class_name != old_class):
            from app.operations import LearnerPlacement
            from datetime import date
            s.add(LearnerPlacement(
                school_id=ctx["sid"], learner_id=learner.id, grade=learner.grade,
                class_name=learner.class_name, reason=placement_reason,
                notes="Bulk update", effective_on=date.today(), recorded_by=ctx["uid"]))
        updated += 1
    m.log(s, ctx, "bulk_update", "learners", updated)
    s.commit()
    return {"updated": updated, "skipped": skipped, "submitted": len(data.rows)}


@router.get("/staff/access-review")
def staff_access_review(s: Session = Depends(m.db), ctx=Depends(m.require(*ADMIN))):
    now = datetime.now(timezone.utc)
    stale_days = 90
    members = s.execute(select(m.Membership, m.User).join(m.User, m.User.id == m.Membership.user_id)
                        .where(m.Membership.school_id == ctx["sid"])
                        .order_by(m.Membership.id)).all()
    items = []
    flags_total = 0
    for mem, user in members:
        last = s.scalar(select(func.max(m.ActiveSession.last_seen_at)).where(
            m.ActiveSession.user_id == user.id, m.ActiveSession.school_id == ctx["sid"]))
        if last is None:
            last = s.scalar(select(func.max(m.ActiveSession.created_at)).where(
                m.ActiveSession.user_id == user.id, m.ActiveSession.school_id == ctx["sid"]))
        flags = []
        if not mem.active:
            flags.append("deactivated")
        if not user.active:
            flags.append("user_inactive")
        if mem.active and last is None:
            flags.append("never_signed_in")
        elif mem.active and last is not None:
            seen = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
            if seen < now - timedelta(days=stale_days):
                flags.append(f"inactive_{stale_days}d")
        if getattr(user, "mfa_enabled", False) is False and mem.role in ("school_admin", "principal", "smt"):
            flags.append("mfa_not_enabled")
        if flags:
            flags_total += 1
        items.append({
            "member_id": mem.id, "user_id": user.id, "email": user.email, "role": mem.role,
            "active": mem.active, "assigned_class": mem.assigned_class or "",
            "mfa_enabled": bool(getattr(user, "mfa_enabled", False)),
            "last_seen_at": last.isoformat() if last else None,
            "flags": flags,
        })
    pending_invites = s.scalar(select(func.count()).select_from(m.StaffInvite).where(
        m.StaffInvite.school_id == ctx["sid"], m.StaffInvite.used == False,
        m.StaffInvite.revoked == False, m.StaffInvite.expires_at > now)) or 0
    reviews = s.scalars(select(StaffAccessReview).where(StaffAccessReview.school_id == ctx["sid"])
                        .order_by(StaffAccessReview.id.desc()).limit(10)).all()
    return {
        "stale_after_days": stale_days,
        "member_count": len(items),
        "flagged_count": flags_total,
        "pending_invites": int(pending_invites),
        "items": items,
        "recent_reviews": [{"id": r.id, "notes": r.notes, "deactivated_count": r.deactivated_count,
                            "member_count": r.member_count, "created_at": r.created_at.isoformat(),
                            "reviewed_by": r.reviewed_by} for r in reviews],
        "notice": "Review flagged accounts at least each term. Deactivation immediately revokes sessions.",
    }


@router.post("/staff/access-review/complete")
def complete_access_review(data: AccessReviewCompleteIn, s: Session = Depends(m.db),
                           ctx=Depends(m.require(*ADMIN))):
    deactivated = 0
    for mid in data.deactivate_member_ids:
        mem = s.scalar(select(m.Membership).where(
            m.Membership.id == mid, m.Membership.school_id == ctx["sid"]))
        if not mem:
            continue
        if mem.user_id == ctx["uid"]:
            raise HTTPException(400, "Cannot deactivate yourself during access review")
        if mem.role == "school_admin" and ctx["role"] != "school_admin":
            raise HTTPException(403, "Only a school administrator can deactivate another administrator")
        if mem.active:
            mem.active = False
            s.execute(delete(m.ActiveSession).where(
                m.ActiveSession.user_id == mem.user_id, m.ActiveSession.school_id == ctx["sid"]))
            deactivated += 1
            m.log(s, ctx, "deactivate", "membership", mem.id)
    member_count = s.scalar(select(func.count()).select_from(m.Membership).where(
        m.Membership.school_id == ctx["sid"])) or 0
    review = StaffAccessReview(
        school_id=ctx["sid"], reviewed_by=ctx["uid"], notes=(data.notes or "").strip(),
        deactivated_count=deactivated, member_count=int(member_count))
    s.add(review); s.flush()
    m.log(s, ctx, "complete", "staff_access_review", review.id)
    s.commit()
    return {"ok": True, "review_id": review.id, "deactivated": deactivated,
            "notice": "Access review recorded. Deactivated staff can no longer sign in to this school."}
