"""Teacher-first shortcuts for quick, human-confirmed incident recording.

Only returns the reporting user's prior structured choices. No learner profiling,
LLM classification or automated disciplinary decisions occur here.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app import main as m

router = APIRouter(prefix="/api/teacher", tags=["teacher"])

@router.get("/incident-shortcuts")
def incident_shortcuts(s: Session = Depends(m.db), ctx=Depends(m.require(
        "educator", "hod", "smt", "principal", "school_admin"))):
    q = (select(m.Incident.offence_id, func.count(m.Incident.id).label("total"))
         .where(m.Incident.school_id == ctx["sid"],
                m.Incident.reporter_id == ctx["uid"])
         .group_by(m.Incident.offence_id)
         .order_by(func.count(m.Incident.id).desc())
         .limit(5))
    common_offence_ids = [row[0] for row in s.execute(q).all()]
    recent = list(s.scalars(select(m.Incident).where(
        m.Incident.school_id == ctx["sid"], m.Incident.reporter_id == ctx["uid"])
        .order_by(m.Incident.id.desc()).limit(20)).all())
    valid_offence_ids = set(s.scalars(select(m.Offence.id).where(
        m.Offence.school_id == ctx["sid"])).all())
    return {
        "favourite_offence_ids": [oid for oid in common_offence_ids if oid in valid_offence_ids],
        "last_location": recent[0].location if recent else None,
        "recent_learner_ids": list(dict.fromkeys(i.learner_id for i in recent))[:5],
        "notice": "Prior selections are suggestions only. Confirm the incident and immediate action before submitting.",
    }
