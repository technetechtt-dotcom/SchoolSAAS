"""Longitudinal learner journey: behaviour + learning/EQ observations from Grade 1 onward.

Supportive profiling only — not a clinical diagnosis tool. Formal IQ/EQ scores may be
recorded when a qualified assessment exists; the platform never invents an IQ score.
"""
from datetime import datetime, timezone, date
from collections import Counter
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import String, ForeignKey, DateTime, Integer, Float, Text, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from app import main as m

router = APIRouter(prefix="/api")
MANAGERS = ("school_admin", "principal", "smt", "hod")

DOMAINS = {
    "reading": "Reading / literacy",
    "numeracy": "Numeracy / counting",
    "emotional_eq": "Emotional intelligence (EQ)",
    "cognitive_assessment": "Formal cognitive / IQ assessment",
    "social": "Social skills",
    "wellbeing": "Wellbeing & regulation",
    "home_factor": "Home context note",
    "school_factor": "School context note",
    "attendance": "Attendance / engagement",
}
FACTORS = ("school", "home", "both", "unknown")
LEVELS = ("emerging", "developing", "secure", "concern", "strength")


class LearnerObservation(m.Base):
    __tablename__ = "learner_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    grade_at_time: Mapped[str] = mapped_column(String(25))
    domain: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(180))
    summary: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String(30), default="developing")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    contributing_factor: Mapped[str] = mapped_column(String(20), default="unknown")
    source: Mapped[str] = mapped_column(String(40), default="classroom_observation")
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ObservationIn(BaseModel):
    learner_id: int
    observed_at: datetime | None = None
    grade_at_time: str = Field(min_length=1, max_length=25)
    domain: str
    title: str = Field(min_length=2, max_length=180)
    summary: str = Field(default="", max_length=4000)
    level: str = "developing"
    score: float | None = Field(default=None, ge=0, le=300)
    contributing_factor: str = "unknown"
    source: str = Field(default="classroom_observation", max_length=40)


class EnrolmentPatch(BaseModel):
    enrolled_on: date | None = None
    grade_started: str | None = Field(default=None, max_length=25)


def _obs_out(x: LearnerObservation):
    return {
        "id": x.id, "learner_id": x.learner_id, "observed_at": x.observed_at.isoformat(),
        "grade_at_time": x.grade_at_time, "domain": x.domain, "domain_label": DOMAINS.get(x.domain, x.domain),
        "title": x.title, "summary": x.summary, "level": x.level, "score": x.score,
        "contributing_factor": x.contributing_factor, "source": x.source,
    }


@router.get("/journey/domains")
def journey_domains(ctx=Depends(m.current)):
    return {
        "domains": [{"id": k, "label": v} for k, v in DOMAINS.items()],
        "factors": list(FACTORS),
        "levels": list(LEVELS),
        "notice": "Formal IQ/EQ scores are recorded only from qualified assessments. "
                  "Classroom observations track reading, numeracy, EQ and context — they are not diagnoses.",
    }


@router.get("/learners/{learner_id}/journey")
def learner_journey(learner_id: int, s: Session = Depends(m.db), ctx=Depends(m.current)):
    learner = s.scalar(select(m.Learner).where(m.Learner.id == learner_id, m.Learner.school_id == ctx["sid"]))
    if not learner:
        raise HTTPException(404, "Learner not found")
    if ctx["role"] == "educator" and learner.class_name not in ctx["assigned_classes"]:
        raise HTTPException(403, "Not assigned to learner")
    sid = ctx["sid"]
    observations = s.scalars(select(LearnerObservation).where(
        LearnerObservation.school_id == sid, LearnerObservation.learner_id == learner.id
    ).order_by(LearnerObservation.observed_at.asc())).all()
    offences = {o.id: o for o in s.scalars(select(m.Offence).where(m.Offence.school_id == sid)).all()}
    incidents = s.scalars(select(m.Incident).where(
        m.Incident.school_id == sid, m.Incident.learner_id == learner.id, m.Incident.status != "withdrawn"
    ).order_by(m.Incident.created_at.asc())).all()
    incident_ids = [i.id for i in incidents]
    interventions = []
    if incident_ids:
        interventions = s.scalars(select(m.Intervention).where(
            m.Intervention.school_id == sid, m.Intervention.incident_id.in_(incident_ids)
        )).all()
    contacts = s.scalars(select(m.ParentContact).where(
        m.ParentContact.school_id == sid, m.ParentContact.learner_id == learner.id
    ).order_by(m.ParentContact.created_at.asc())).all()

    timeline = []
    for o in observations:
        timeline.append({
            "at": o.observed_at.isoformat(), "kind": "observation", "domain": o.domain,
            "title": o.title, "detail": o.summary, "grade": o.grade_at_time,
            "level": o.level, "factor": o.contributing_factor, "score": o.score, "id": o.id,
        })
    for i in incidents:
        off = offences.get(i.offence_id)
        timeline.append({
            "at": i.created_at.isoformat(), "kind": "incident", "domain": "behaviour",
            "title": (off.code + " · " + off.name) if off else "Incident",
            "detail": i.description, "grade": learner.grade, "level": str(off.severity) if off else "",
            "factor": "school", "id": i.id, "public_ref": getattr(i, "public_ref", None),
        })
    for c in contacts:
        timeline.append({
            "at": c.created_at.isoformat(), "kind": "parent_contact", "domain": "home_factor",
            "title": c.purpose, "detail": f"{c.method}: {c.outcome}", "grade": learner.grade,
            "level": "", "factor": "home", "id": c.id,
        })
    for iv in interventions:
        at = iv.due_at or datetime.now(timezone.utc)
        timeline.append({
            "at": at.isoformat(), "kind": "intervention",
            "domain": "wellbeing", "title": iv.type, "detail": iv.notes or iv.outcome,
            "grade": learner.grade, "level": iv.outcome, "factor": "school", "id": iv.id,
        })
    timeline.sort(key=lambda x: x["at"])

    progress = {}
    for domain in ("reading", "numeracy", "emotional_eq", "cognitive_assessment", "social", "attendance"):
        series = [{
            "at": o.observed_at.isoformat()[:10], "grade": o.grade_at_time, "level": o.level,
            "score": o.score, "title": o.title, "factor": o.contributing_factor,
        } for o in observations if o.domain == domain]
        if series:
            progress[domain] = {"label": DOMAINS[domain], "points": series, "latest": series[-1]}

    factor_counts = Counter(o.contributing_factor for o in observations if o.contributing_factor in FACTORS)
    behaviour_years = Counter(
        (i.created_at.year, getattr(offences.get(i.offence_id), "category", "?")) for i in incidents
    )

    insights = []
    reading = progress.get("reading", {}).get("latest")
    numeracy = progress.get("numeracy", {}).get("latest")
    eq = progress.get("emotional_eq", {}).get("latest")
    if reading and reading["level"] in ("concern", "emerging"):
        insights.append({
            "theme": "Reading / literacy",
            "signal": reading["title"],
            "ask": "Is the barrier instructional (school), language exposure at home, vision/hearing, or attendance?",
            "factor_hint": reading.get("factor") or "unknown",
        })
    if numeracy and numeracy["level"] in ("concern", "emerging"):
        insights.append({
            "theme": "Numeracy / counting",
            "signal": numeracy["title"],
            "ask": "Check number-sense teaching, concrete materials, maths anxiety, and home practice patterns.",
            "factor_hint": numeracy.get("factor") or "unknown",
        })
    if eq and eq["level"] in ("concern", "emerging"):
        insights.append({
            "theme": "Emotional regulation (EQ)",
            "signal": eq["title"],
            "ask": "Explore classroom relationships, trauma-informed support, and home routines or stress.",
            "factor_hint": eq.get("factor") or "unknown",
        })
    if factor_counts.get("home", 0) >= 2 and factor_counts.get("school", 0) >= 2:
        insights.append({
            "theme": "Mixed school and home factors",
            "signal": "Multiple notes cite both settings",
            "ask": "Coordinate parent partnership with classroom adjustments — avoid blaming one setting alone.",
            "factor_hint": "both",
        })
    if not insights and observations:
        insights.append({
            "theme": "Ongoing monitoring",
            "signal": "Journey records exist from early grades",
            "ask": "Use the timeline to celebrate growth and spot early dips in reading, counting, or emotional confidence.",
            "factor_hint": "unknown",
        })

    enrolled_on = getattr(learner, "enrolled_on", None)
    grade_started = getattr(learner, "grade_started", None) or "1"
    return {
        "learner_id": learner.id,
        "name": learner.first_name + " " + learner.surname,
        "current_grade": learner.grade,
        "class_name": learner.class_name,
        "admission_no": learner.admission_no,
        "enrolled_on": enrolled_on.isoformat() if enrolled_on else None,
        "grade_started": grade_started,
        "notice": "This journey supports understanding — it does not diagnose learning disabilities or invent an IQ. "
                  "Formal cognitive/EQ scores appear only when entered from qualified assessments.",
        "factor_summary": dict(factor_counts),
        "progress": progress,
        "insights": insights,
        "timeline": timeline[-80:],
        "observations": [_obs_out(o) for o in observations],
        "behaviour_by_year_category": [
            {"year": y, "category": cat, "count": n} for (y, cat), n in sorted(behaviour_years.items())
        ],
    }


@router.post("/learners/{learner_id}/observations", status_code=201)
def add_observation(learner_id: int, data: ObservationIn, s: Session = Depends(m.db), ctx=Depends(m.require(*MANAGERS))):
    if data.learner_id != learner_id:
        raise HTTPException(400, "Learner id mismatch")
    if data.domain not in DOMAINS:
        raise HTTPException(400, "Unknown observation domain")
    if data.level not in LEVELS:
        raise HTTPException(400, "Invalid level")
    if data.contributing_factor not in FACTORS:
        raise HTTPException(400, "Invalid contributing factor")
    if data.domain == "cognitive_assessment" and data.score is None and not data.summary.strip():
        raise HTTPException(400, "Formal cognitive/IQ entries need a professional score or assessment summary")
    learner = s.scalar(select(m.Learner).where(m.Learner.id == learner_id, m.Learner.school_id == ctx["sid"]))
    if not learner:
        raise HTTPException(404, "Learner not found")
    obs = LearnerObservation(
        school_id=ctx["sid"], learner_id=learner_id, recorded_by=ctx["uid"],
        observed_at=data.observed_at or datetime.now(timezone.utc),
        grade_at_time=data.grade_at_time.strip(), domain=data.domain, title=data.title.strip(),
        summary=data.summary.strip(), level=data.level, score=data.score,
        contributing_factor=data.contributing_factor, source=data.source,
    )
    s.add(obs)
    s.flush()
    m.log(s, ctx, "create", "learner_observation", obs.id)
    s.commit()
    return {"id": obs.id}


@router.patch("/learners/{learner_id}/enrolment")
def patch_enrolment(learner_id: int, data: EnrolmentPatch, s: Session = Depends(m.db),
                    ctx=Depends(m.require("school_admin", "principal", "smt", "hod"))):
    learner = s.scalar(select(m.Learner).where(m.Learner.id == learner_id, m.Learner.school_id == ctx["sid"]))
    if not learner:
        raise HTTPException(404, "Learner not found")
    if data.enrolled_on is not None:
        learner.enrolled_on = data.enrolled_on
    if data.grade_started is not None:
        learner.grade_started = data.grade_started.strip() or None
    m.log(s, ctx, "update", "learner_enrolment", learner.id)
    s.commit()
    return {
        "ok": True,
        "enrolled_on": learner.enrolled_on.isoformat() if learner.enrolled_on else None,
        "grade_started": learner.grade_started,
    }
