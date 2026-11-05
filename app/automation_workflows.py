"""Prepare management-owned referral drafts from a single incident.

These are editable drafts, not disciplinary decisions or outbound communications.
"""
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
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
