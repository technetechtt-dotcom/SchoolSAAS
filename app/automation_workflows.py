"""Prepare management-owned referral drafts from a single incident.

These are editable drafts, not disciplinary decisions or outbound communications.
"""
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from datetime import datetime,timezone,timedelta
from app import main as m
from app.extended import SchoolDocument

router=APIRouter(prefix="/api/automation",tags=["automation"])
MANAGERS=("school_admin","principal","smt","hod")

@router.post("/incidents/{incident_id}/referral-draft",status_code=201)
def prepare_referral(incident_id:int,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    incident=s.scalar(select(m.Incident).where(
        m.Incident.id==incident_id,m.Incident.school_id==ctx["sid"]))
    if not incident:raise HTTPException(404,"Incident not found")
    learner=s.scalar(select(m.Learner).where(
        m.Learner.id==incident.learner_id,m.Learner.school_id==ctx["sid"]))
    offence=s.scalar(select(m.Offence).where(
        m.Offence.id==incident.offence_id,m.Offence.school_id==ctx["sid"]))
    reporter=s.get(m.User,incident.reporter_id)
    if not learner or not offence:raise HTTPException(409,"Incident references incomplete school records")
    reference=incident.public_ref or f"#{incident.id}"
    title=f"Referral draft for incident {reference}"
    existing=s.scalar(select(SchoolDocument).where(
        SchoolDocument.school_id==ctx["sid"],SchoolDocument.learner_id==learner.id,
        SchoolDocument.document_type=="referral",SchoolDocument.title==title,
        SchoolDocument.status=="draft"))
    if existing:return {"id":existing.id,"status":"draft","reused":True}
    body=(
        f"REFERRAL DRAFT — FOR AUTHORISED SCHOOL REVIEW\n"
        f"School: {ctx['school']}\nIncident reference: {reference}\n"
        f"Learner: {learner.first_name} {learner.surname}\n"
        f"Grade / class: {learner.grade} / {learner.class_name}\n"
        f"Reported by: {reporter.email if reporter else 'School staff'}\n"
        f"Location: {incident.location}\nCategory: {offence.code} — {offence.name}\n"
        f"Description reported: {incident.description}\n"
        f"Immediate action reported: {incident.immediate_action}\n"
        f"Review flag: {incident.flag_reason or 'None'}\n\n"
        "Management review required: confirm facts, applicable policy, support needs, "
        "next actions and guardian communication before any formal action.\n"
        "This draft is not a finding of misconduct or a disciplinary sanction.\n"
    )
    record=SchoolDocument(school_id=ctx["sid"],learner_id=learner.id,
        title=title,body=body,document_type="referral",status="draft")
    s.add(record);s.flush();m.log(s,ctx,"prepare","referral_document",record.id)
    s.commit()
    return {"id":record.id,"status":"draft","reused":False}


@router.get("/followups/due")
def due_followups(s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    from app.operations import FollowUp
    today=datetime.now(timezone.utc)
    cutoff=today+timedelta(days=2)
    rows=s.scalars(select(FollowUp).where(
        FollowUp.school_id==ctx["sid"],FollowUp.status.in_(("open","in_progress")),
        FollowUp.due_at<=cutoff).order_by(FollowUp.due_at).limit(100)).all()
    return {"items":[{"id":x.id,"case_id":x.case_id,"owner_user_id":x.owner_user_id,
                      "due_at":x.due_at.isoformat(),"summary":x.summary,
                      "overdue":x.due_at.replace(tzinfo=timezone.utc)<today}
                     for x in rows],
            "notice":"Staff must verify case decisions. Reminders do not perform actions automatically."}

@router.post("/followups/queue-reminders")
def queue_followup_reminders(s:Session=Depends(m.db),
                            ctx=Depends(m.require("school_admin","principal"))):
    """Queue non-sensitive staff reminders for due/overdue work; never email child details."""
    from app.operations import FollowUp
    from app.mail_outbox import EmailOutbox,enqueue_email
    now=datetime.now(timezone.utc)
    rows=s.scalars(select(FollowUp).where(
        FollowUp.school_id==ctx["sid"],
        FollowUp.status.in_(("open","in_progress")),
        FollowUp.due_at<=now+timedelta(days=2)).limit(200)).all()
    queued=skipped=0
    for x in rows:
        member=s.scalar(select(m.Membership).where(
            m.Membership.school_id==ctx["sid"],m.Membership.user_id==x.owner_user_id,
            m.Membership.active==True))
        user=s.get(m.User,x.owner_user_id)
        if not member or not user or not user.active:
            skipped+=1;continue
        date=now.date().isoformat()
        subject=f"SchoolSAAS task reminder #{x.id} ({date})"
        existing=s.scalar(select(EmailOutbox).where(
            EmailOutbox.school_id==ctx["sid"],EmailOutbox.destination==user.email,
            EmailOutbox.subject==subject))
        if existing:
            skipped+=1;continue
        body=(f"You have a school follow-up task requiring review.\\n"
              f"Case reference: #{x.case_id}\\n"
              f"Due: {x.due_at.isoformat()}\\n"
              "Sign in to your SchoolSAAS account to view details. "
              "No learner details are included in this email.")
        enqueue_email(s,user.email,subject,body,ctx["sid"])
        queued+=1
    m.log(s,ctx,"queue_reminders","follow_up",queued)
    s.commit()
    return {"queued":queued,"skipped":skipped,
            "notice":"Reminders queued for approved SMTP delivery; no disciplinary decisions made."}
