"""School onboarding progress and setup completeness checks."""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import String, ForeignKey, DateTime, Boolean, Text, select, func
from sqlalchemy.orm import Mapped, mapped_column, Session
from app import main as m
from app.pilot_pack import ConductVersion, LetterTemplate

router = APIRouter(prefix="/api")
ADMIN = ("school_admin", "principal")
MANAGERS = ("school_admin", "principal", "smt", "hod")


class OnboardingMarkIn(BaseModel):
    step_id: str = Field(min_length=2, max_length=60)
    completed: bool = True
    notes: str = Field(default="", max_length=500)


class OnboardingStep(m.Base):
    __tablename__ = "onboarding_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    step_id: Mapped[str] = mapped_column(String(60))
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


STEPS = [
    ("school_profile", "Confirm school profile and contact email", True),
    ("academic_year", "Set academic year and current term", True),
    ("offence_catalogue", "Configure at least one offence code", True),
    ("code_of_conduct", "Approve a Code of Conduct version", True),
    ("staff_access", "Invite or confirm staff memberships", True),
    ("learners_imported", "Register or import learners", True),
    ("behaviour_settings", "Review progressive-discipline thresholds", False),
    ("parent_comms", "Prepare parent communication / letter templates", False),
]


def _settings_map(s: Session, sid: int) -> dict[str, str]:
    return {x.key: x.value for x in s.scalars(select(m.SchoolSetting).where(m.SchoolSetting.school_id == sid)).all()}


def compute_onboarding(s: Session, ctx: dict) -> dict:
    sid = ctx["sid"]
    settings = _settings_map(s, sid)
    school = s.get(m.School, sid)
    offences = s.scalar(select(func.count()).select_from(m.Offence).where(m.Offence.school_id == sid)) or 0
    members = s.scalar(select(func.count()).select_from(m.Membership).where(
        m.Membership.school_id == sid, m.Membership.active == True)) or 0
    learners = s.scalar(select(func.count()).select_from(m.Learner).where(m.Learner.school_id == sid)) or 0
    approved_coc = s.scalar(select(func.count()).select_from(ConductVersion).where(
        ConductVersion.school_id == sid, ConductVersion.approved == True)) or 0
    templates = s.scalar(select(func.count()).select_from(LetterTemplate).where(LetterTemplate.school_id == sid)) or 0
    auto = {
        "school_profile": bool(settings.get("school_contact_email") or (school and school.name)),
        "academic_year": bool(settings.get("academic_year") and settings.get("term")),
        "offence_catalogue": offences >= 1,
        "code_of_conduct": approved_coc >= 1,
        "staff_access": members >= 1,
        "learners_imported": learners >= 1,
        "behaviour_settings": bool(settings.get("repeat_window_days") or settings.get("repeat_threshold")),
        "parent_comms": templates >= 1,
    }
    manual = {x.step_id: x for x in s.scalars(select(OnboardingStep).where(OnboardingStep.school_id == sid)).all()}
    items = []
    required_done = 0
    required_total = 0
    for step_id, label, required in STEPS:
        done = bool(auto.get(step_id)) or bool(getattr(manual.get(step_id), "completed", False))
        if required:
            required_total += 1
            if done:
                required_done += 1
        items.append({
            "id": step_id, "label": label, "required": required, "completed": done,
            "auto_detected": bool(auto.get(step_id)),
            "notes": getattr(manual.get(step_id), "notes", "") or "",
        })
    complete = required_done == required_total and required_total > 0
    return {
        "school_id": sid,
        "school_name": school.name if school else "",
        "complete": complete,
        "progress_percent": int(round(100 * required_done / required_total)) if required_total else 0,
        "required_done": required_done,
        "required_total": required_total,
        "items": items,
        "message": (
            "School setup is complete. Sensitive discipline workflows may proceed under authorised staff review."
            if complete else
            "Complete required onboarding steps before treating this school as fully operational."
        ),
    }


def assert_onboarding_complete(s: Session, ctx: dict, workflow: str = "this workflow"):
    """Block sensitive formal workflows until required school setup is complete."""
    status = compute_onboarding(s, ctx)
    if status["complete"]:
        return status
    outstanding = [x["id"] for x in status["items"] if x["required"] and not x["completed"]]
    raise HTTPException(
        409,
        f"Complete school setup before {workflow}. Outstanding: " + (", ".join(outstanding) or "required steps"),
    )


@router.get("/onboarding/status")
def onboarding_status(s: Session = Depends(m.db), ctx=Depends(m.require(*MANAGERS))):
    return compute_onboarding(s, ctx)


@router.post("/onboarding/steps")
def mark_onboarding_step(data: OnboardingMarkIn, s: Session = Depends(m.db), ctx=Depends(m.require(*ADMIN))):
    if data.step_id not in {x[0] for x in STEPS}:
        raise HTTPException(400, "Unknown onboarding step")
    item = s.scalar(select(OnboardingStep).where(
        OnboardingStep.school_id == ctx["sid"], OnboardingStep.step_id == data.step_id))
    if not item:
        item = OnboardingStep(school_id=ctx["sid"], step_id=data.step_id)
        s.add(item)
    item.completed = data.completed
    item.notes = data.notes.strip()
    item.updated_at = datetime.now(timezone.utc)
    m.log(s, ctx, "update", "onboarding_step", ctx["sid"])
    s.commit()
    return compute_onboarding(s, ctx)
