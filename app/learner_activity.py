"""Unified learner activity timeline across discipline, support and communications."""
from __future__ import annotations
from datetime import datetime, timezone, date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import main as m

router = APIRouter(prefix="/api")
MANAGERS = ("school_admin", "principal", "smt", "hod")
FALLBACK_AT = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _iso(value) -> str:
    if value is None:
        return FALLBACK_AT.isoformat()
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _entry(at, kind: str, title: str, detail: str = "", ref_type: str = "", ref_id: int | None = None,
           status: str = "") -> dict:
    return {
        "at": _iso(at), "kind": kind, "title": title, "detail": (detail or "")[:500],
        "ref_type": ref_type, "ref_id": ref_id, "status": status or "",
    }


@router.get("/learners/{learner_id}/activity")
def learner_activity(learner_id: int, limit: int = Query(100, ge=10, le=300),
                     s: Session = Depends(m.db), ctx=Depends(m.current)):
    learner = s.scalar(select(m.Learner).where(m.Learner.id == learner_id, m.Learner.school_id == ctx["sid"]))
    if not learner:
        raise HTTPException(404, "Learner not found")
    if ctx["role"] == "educator" and learner.class_name not in ctx.get("assigned_classes", []):
        raise HTTPException(403, "Not assigned to learner")

    sid = ctx["sid"]
    items: list[dict] = []
    is_manager = ctx["role"] in MANAGERS

    enrolled = getattr(learner, "enrolled_on", None)
    if enrolled:
        items.append(_entry(enrolled, "enrolment",
                            f"Enrolled (started Grade {getattr(learner, 'grade_started', None) or learner.grade})",
                            ref_type="learner", ref_id=learner.id,
                            status="active" if learner.active else "inactive"))

    incidents = list(s.scalars(select(m.Incident).where(
        m.Incident.school_id == sid, m.Incident.learner_id == learner.id)
        .order_by(m.Incident.id.desc()).limit(80)).all())
    if ctx["role"] == "educator":
        incidents = [i for i in incidents if i.reporter_id == ctx["uid"]]
    offence_names = {o.id: o.name for o in s.scalars(select(m.Offence).where(m.Offence.school_id == sid)).all()}
    incident_ids = [i.id for i in incidents]
    for i in incidents:
        items.append(_entry(i.created_at, "incident",
                            f"Incident · {offence_names.get(i.offence_id, 'Offence')}",
                            i.description or i.location or "",
                            "incident", i.id, i.status))

    if is_manager:
        cases = list(s.scalars(select(m.Case).where(
            m.Case.school_id == sid, m.Case.learner_id == learner.id).limit(50)).all())
        case_ids = [c.id for c in cases]
        for c in cases:
            items.append(_entry(FALLBACK_AT, "case", c.title, "", "case", c.id, c.status))

        from app.operations import CaseEvent, LearnerPlacement
        if case_ids:
            events = s.scalars(select(CaseEvent).where(
                CaseEvent.school_id == sid, CaseEvent.case_id.in_(case_ids))
                .order_by(CaseEvent.id.desc()).limit(80)).all()
            for e in events:
                items.append(_entry(e.created_at, "case_note", f"Case note · {e.kind}",
                                    e.note or "", "case", e.case_id, e.kind))
        placements = s.scalars(select(LearnerPlacement).where(
            LearnerPlacement.school_id == sid, LearnerPlacement.learner_id == learner.id)
            .order_by(LearnerPlacement.id.desc()).limit(40)).all()
        for p in placements:
            items.append(_entry(p.effective_on, "placement",
                                f"Placement · {p.reason}",
                                f"Grade {p.grade} / {p.class_name}. {p.notes or ''}".strip(),
                                "learner", learner.id, p.reason))

        contacts = s.scalars(select(m.ParentContact).where(
            m.ParentContact.school_id == sid, m.ParentContact.learner_id == learner.id)
            .order_by(m.ParentContact.id.desc()).limit(40)).all()
        for x in contacts:
            items.append(_entry(x.created_at, "parent_contact", x.purpose,
                                f"{x.method}: {x.outcome}", "parent_contact", x.id))

        if incident_ids:
            interventions = s.scalars(select(m.Intervention).where(
                m.Intervention.school_id == sid, m.Intervention.incident_id.in_(incident_ids))
                .order_by(m.Intervention.id.desc()).limit(60)).all()
            for x in interventions:
                items.append(_entry(x.due_at or FALLBACK_AT, "intervention", x.type, x.notes or "",
                                    "intervention", x.id, x.outcome))

        from app.extended import Appointment, SchoolDocument, Appeal
        for x in s.scalars(select(Appointment).where(
                Appointment.school_id == sid, Appointment.learner_id == learner.id)
                .order_by(Appointment.id.desc()).limit(30)).all():
            items.append(_entry(x.scheduled_at, "meeting", x.title, "", "appointment", x.id, x.status))
        for x in s.scalars(select(SchoolDocument).where(
                SchoolDocument.school_id == sid, SchoolDocument.learner_id == learner.id)
                .order_by(SchoolDocument.id.desc()).limit(30)).all():
            items.append(_entry(x.created_at, "document", x.title, x.document_type,
                                "document", x.id, getattr(x, "status", "draft") or "draft"))
        if case_ids:
            for x in s.scalars(select(Appeal).where(
                    Appeal.school_id == sid, Appeal.case_id.in_(case_ids)).limit(20)).all():
                items.append(_entry(x.created_at, "appeal", "Appeal lodged", x.reason[:200],
                                    "appeal", x.id, x.status))

        from app.pilot_pack import Hearing, ParentAccess, ParentAck, ParentDispute
        if case_ids:
            for x in s.scalars(select(Hearing).where(
                    Hearing.school_id == sid, Hearing.case_id.in_(case_ids)).limit(20)).all():
                items.append(_entry(x.scheduled_at, "hearing", f"Hearing · {x.chair or 'panel'}",
                                    x.outcome or x.notes or "", "hearing", x.id, x.status))
        for x in s.scalars(select(ParentAccess).where(
                ParentAccess.school_id == sid, ParentAccess.learner_id == learner.id)
                .order_by(ParentAccess.id.desc()).limit(30)).all():
            created = getattr(x, "created_at", None) or x.expires_at
            items.append(_entry(created, "parent_notice", x.subject,
                                f"Delivered to {x.email}", "parent_notice", x.id,
                                "acknowledged" if x.used else "pending"))
        for x in s.scalars(select(ParentAck).where(
                ParentAck.school_id == sid, ParentAck.learner_id == learner.id).limit(30)).all():
            items.append(_entry(x.acknowledged_at, "parent_ack", x.subject,
                                x.email, "parent_ack", x.id, "acknowledged"))
        for x in s.scalars(select(ParentDispute).where(
                ParentDispute.school_id == sid, ParentDispute.learner_id == learner.id).limit(20)).all():
            items.append(_entry(x.created_at, "parent_dispute", x.subject, x.reason[:200],
                                "parent_dispute", x.id, x.status))

        from app.letter_workflow import LetterDocument
        for x in s.scalars(select(LetterDocument).where(
                LetterDocument.school_id == sid, LetterDocument.learner_id == learner.id)
                .order_by(LetterDocument.id.desc()).limit(30)).all():
            items.append(_entry(x.created_at, "letter", x.title,
                                x.delivery_notes or x.delivery_to or "",
                                "letter_document", x.id, x.status))

        from app.learner_journey import LearnerObservation
        for x in s.scalars(select(LearnerObservation).where(
                LearnerObservation.school_id == sid, LearnerObservation.learner_id == learner.id)
                .order_by(LearnerObservation.id.desc()).limit(40)).all():
            items.append(_entry(x.observed_at or x.created_at, "observation",
                                f"{x.domain}: {x.title}", x.summary or "",
                                "observation", x.id, x.level or ""))

    items.sort(key=lambda x: x["at"] or "", reverse=True)
    items = items[:limit]
    m.log(s, ctx, "view", "learner_activity", learner.id)
    s.commit()
    return {
        "learner_id": learner.id,
        "learner_name": f"{learner.first_name} {learner.surname}",
        "count": len(items),
        "items": items,
        "notice": (
            "School-wide activity feed for authorised managers."
            if is_manager else
            "Educator view shows incidents you reported for assigned classes only."
        ),
    }
