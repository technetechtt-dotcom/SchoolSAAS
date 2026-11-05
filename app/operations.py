"""School operations added after the v0.4 foundation.

All personally identifying and learner support records are school-scoped.
No automated sanction or disciplinary decision is made by these endpoints.
"""
from datetime import datetime, timezone, date, time, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, Text, DateTime, ForeignKey, UniqueConstraint, select, func
from sqlalchemy.orm import Mapped, mapped_column, Session
from app import main as m
from app.extended import school_record, MANAGERS, ADMIN

router=APIRouter(prefix="/api")
def now():return datetime.now(timezone.utc)
def require_learner(s, learner_id, sid):
    return school_record(s,m.Learner,learner_id,sid)

class Guardian(m.Base):
    __tablename__="guardians"
    __table_args__=(UniqueConstraint("school_id","learner_id","email"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    school_id:Mapped[int]=mapped_column(ForeignKey("schools.id"),index=True)
    learner_id:Mapped[int]=mapped_column(ForeignKey("learners.id"),index=True)
    name:Mapped[str]=mapped_column(String(150))
    relationship:Mapped[str]=mapped_column(String(60))
    email:Mapped[str]=mapped_column(String(255))
    phone:Mapped[str]=mapped_column(String(40),default="")
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class CaseEvent(m.Base):
    __tablename__="case_events"
    id:Mapped[int]=mapped_column(primary_key=True)
    school_id:Mapped[int]=mapped_column(ForeignKey("schools.id"),index=True)
    case_id:Mapped[int]=mapped_column(ForeignKey("cases.id"),index=True)
    author_user_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    kind:Mapped[str]=mapped_column(String(40))
    note:Mapped[str]=mapped_column(Text)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class FollowUp(m.Base):
    __tablename__="follow_ups"
    id:Mapped[int]=mapped_column(primary_key=True)
    school_id:Mapped[int]=mapped_column(ForeignKey("schools.id"),index=True)
    case_id:Mapped[int]=mapped_column(ForeignKey("cases.id"),index=True)
    owner_user_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    summary:Mapped[str]=mapped_column(String(240))
    due_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    status:Mapped[str]=mapped_column(String(30),default="open")
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class ClassAssignment(m.Base):
    __tablename__="class_assignments"
    __table_args__=(UniqueConstraint("school_id","user_id","class_name"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    school_id:Mapped[int]=mapped_column(ForeignKey("schools.id"),index=True)
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id"),index=True)
    class_name:Mapped[str]=mapped_column(String(30))

class GuardianIn(BaseModel):
    learner_id:int
    name:str=Field(min_length=2,max_length=150)
    relationship:str=Field(min_length=2,max_length=60)
    email:str=Field(min_length=5,max_length=255)
    phone:str=Field(default="",max_length=40)

class CaseEventIn(BaseModel):
    kind:str=Field(default="note")
    note:str=Field(min_length=3,max_length=4000)

class FollowUpIn(BaseModel):
    summary:str=Field(min_length=3,max_length=240)
    due_at:datetime
    owner_user_id:int

class FollowUpUpdate(BaseModel):
    status:str

class ClassAssignmentIn(BaseModel):
    user_id:int
    class_name:str=Field(min_length=1,max_length=30)

def member(s,user_id,sid):
    found=s.scalar(select(m.Membership).where(m.Membership.school_id==sid,m.Membership.user_id==user_id,m.Membership.active==True))
    user=s.get(m.User,user_id)
    if not found or not user or not user.active:raise HTTPException(400,"Not an active school member")
    return found

@router.get("/guardians")
def guardians(learner_id:int,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    require_learner(s,learner_id,ctx["sid"])
    rows=s.scalars(select(Guardian).where(Guardian.school_id==ctx["sid"],Guardian.learner_id==learner_id)).all()
    m.log(s,ctx,"view","guardian_directory",learner_id);s.commit()
    return [{"id":x.id,"name":x.name,"relationship":x.relationship,"email":x.email,"phone":x.phone} for x in rows]

@router.post("/guardians",status_code=201)
def add_guardian(data:GuardianIn,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    require_learner(s,data.learner_id,ctx["sid"])
    x=Guardian(school_id=ctx["sid"],**data.model_dump())
    s.add(x);s.flush();m.log(s,ctx,"create","guardian",x.id);s.commit();return {"id":x.id}

@router.get("/cases/{case_id}/timeline")
def timeline(case_id:int,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    school_record(s,m.Case,case_id,ctx["sid"])
    rows=s.scalars(select(CaseEvent).where(CaseEvent.school_id==ctx["sid"],CaseEvent.case_id==case_id).order_by(CaseEvent.created_at,CaseEvent.id)).all()
    return [{"id":x.id,"kind":x.kind,"note":x.note,"author_user_id":x.author_user_id,"created_at":x.created_at.isoformat()} for x in rows]

@router.post("/cases/{case_id}/timeline",status_code=201)
def add_event(case_id:int,data:CaseEventIn,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    school_record(s,m.Case,case_id,ctx["sid"])
    if data.kind not in ("note","meeting","referral","decision","evidence_reference","appeal"):
        raise HTTPException(400,"Invalid event type")
    x=CaseEvent(school_id=ctx["sid"],case_id=case_id,author_user_id=ctx["uid"],**data.model_dump())
    s.add(x);s.flush();m.log(s,ctx,"create","case_event",x.id);s.commit();return {"id":x.id}

@router.get("/cases/{case_id}/follow-ups")
def list_followups(case_id:int,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    school_record(s,m.Case,case_id,ctx["sid"])
    rows=s.scalars(select(FollowUp).where(FollowUp.school_id==ctx["sid"],FollowUp.case_id==case_id).order_by(FollowUp.due_at)).all()
    return [{"id":x.id,"summary":x.summary,"owner_user_id":x.owner_user_id,"due_at":x.due_at.isoformat(),"status":x.status} for x in rows]

@router.post("/cases/{case_id}/follow-ups",status_code=201)
def add_followup(case_id:int,data:FollowUpIn,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    school_record(s,m.Case,case_id,ctx["sid"]);member(s,data.owner_user_id,ctx["sid"])
    if data.due_at.tzinfo is None:raise HTTPException(422,"Date must include a time zone")
    x=FollowUp(school_id=ctx["sid"],case_id=case_id,**data.model_dump())
    s.add(x);s.flush();m.log(s,ctx,"create","follow_up",x.id);s.commit();return {"id":x.id}

@router.patch("/follow-ups/{follow_up_id}")
def update_followup(follow_up_id:int,data:FollowUpUpdate,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    x=school_record(s,FollowUp,follow_up_id,ctx["sid"])
    if data.status not in ("open","in_progress","completed","cancelled"):raise HTTPException(400,"Invalid status")
    if ctx["role"]=="hod" and x.owner_user_id!=ctx["uid"]:raise HTTPException(403,"Only assigned HOD can update this follow-up")
    x.status=data.status;m.log(s,ctx,"update","follow_up",x.id);s.commit();return {"ok":True}

@router.get("/class-assignments")
def assignments(s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    rows=s.execute(
        select(ClassAssignment,m.User,m.Membership)
        .join(m.User,m.User.id==ClassAssignment.user_id)
        .outerjoin(m.Membership,(m.Membership.user_id==ClassAssignment.user_id)&(m.Membership.school_id==ctx["sid"]))
        .where(ClassAssignment.school_id==ctx["sid"])
        .order_by(m.User.email,ClassAssignment.class_name)
    ).all()
    return [{"id":a.id,"user_id":a.user_id,"class_name":a.class_name,
             "email":user.email,"role":(member.role if member else None)}
            for a,user,member in rows]

@router.post("/class-assignments",status_code=201)
def assign_class(data:ClassAssignmentIn,s:Session=Depends(m.db),ctx=Depends(m.require(*ADMIN))):
    member(s,data.user_id,ctx["sid"])
    x=s.scalar(select(ClassAssignment).where(ClassAssignment.school_id==ctx["sid"],ClassAssignment.user_id==data.user_id,ClassAssignment.class_name==data.class_name))
    if x:raise HTTPException(409,"Already assigned")
    x=ClassAssignment(school_id=ctx["sid"],**data.model_dump())
    s.add(x);s.flush();m.log(s,ctx,"create","class_assignment",x.id);s.commit();return {"id":x.id}

@router.delete("/class-assignments/{assignment_id}")
def unassign_class(assignment_id:int,s:Session=Depends(m.db),ctx=Depends(m.require(*ADMIN))):
    x=school_record(s,ClassAssignment,assignment_id,ctx["sid"])
    s.delete(x);m.log(s,ctx,"delete","class_assignment",assignment_id);s.commit();return {"ok":True}

@router.get("/cases/{case_id}/closure-checklist")
def case_closure_checklist(case_id:int,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    case=school_record(s,m.Case,case_id,ctx["sid"])
    events=s.scalars(select(CaseEvent).where(CaseEvent.school_id==ctx["sid"],CaseEvent.case_id==case.id)).all()
    followups=s.scalars(select(FollowUp).where(FollowUp.school_id==ctx["sid"],FollowUp.case_id==case.id)).all()
    from app.pilot_pack import Hearing, EvidenceFile
    hearings=s.scalars(select(Hearing).where(Hearing.school_id==ctx["sid"],Hearing.case_id==case.id)).all()
    evidence=s.scalars(select(EvidenceFile).where(EvidenceFile.school_id==ctx["sid"],EvidenceFile.case_id==case.id)).all()
    open_followups=[f for f in followups if f.status in ("open","in_progress")]
    decision_notes=[e for e in events if e.kind in ("decision","referral")]
    completed_hearing=any(h.status=="completed" and (h.outcome or "").strip() for h in hearings)
    items=[
        {"id":"assigned","label":"Case assigned to authorised staff","required":True,"done":bool(case.assigned_user_id)},
        {"id":"timeline","label":"At least one timeline note or decision recorded","required":True,"done":len(events)>0},
        {"id":"decision","label":"Formal decision / referral note on timeline","required":True,"done":len(decision_notes)>0},
        {"id":"followups","label":"No open follow-up tasks","required":True,"done":len(open_followups)==0},
        {"id":"hearing","label":"Hearing completed with human outcome (when formal process)","required":case.status in ("formal_process","smt_review","awaiting_outcome"),
         "done":completed_hearing or case.status not in ("formal_process","smt_review","awaiting_outcome")},
        {"id":"evidence","label":"Evidence attached (recommended)","required":False,"done":len(evidence)>0},
    ]
    blocking=[i for i in items if i["required"] and not i["done"]]
    return {"case_id":case.id,"status":case.status,"ready_to_close":len(blocking)==0 and case.status!="closed",
            "blocking":[i["id"] for i in blocking],"items":items}


@router.post("/cases/{case_id}/close")
def close_case(case_id:int,s:Session=Depends(m.db),ctx=Depends(m.require("school_admin","principal","smt"))):
    case=school_record(s,m.Case,case_id,ctx["sid"])
    if case.status=="closed":
        return {"ok":True,"status":"closed","message":"Already closed"}
    checklist=case_closure_checklist(case_id,s,ctx)
    if not checklist["ready_to_close"]:
        raise HTTPException(409,"Closure checklist incomplete: "+", ".join(checklist["blocking"]))
    previous=case.status
    case.status="closed"
    s.add(CaseEvent(school_id=ctx["sid"],case_id=case.id,author_user_id=ctx["uid"],kind="decision",
                    note=f"Case closed by authorised staff (from {previous}). Checklist verified."))
    m.log(s,ctx,"close","case",case.id);s.commit()
    return {"ok":True,"status":"closed"}


@router.get("/directory/incidents")
def paged_incidents(limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),
                    s:Session=Depends(m.db),ctx=Depends(m.current)):
    q=select(m.Incident).where(m.Incident.school_id==ctx["sid"])
    if ctx["role"]=="educator":q=q.where(m.Incident.reporter_id==ctx["uid"])
    total=s.scalar(select(func.count()).select_from(q.subquery()))
    rows=s.scalars(q.order_by(m.Incident.id.desc()).offset(offset).limit(limit)).all()
    return {"total":total,"offset":offset,"limit":limit,"items":[{"id":x.id,"learner_id":x.learner_id,"offence_id":x.offence_id,"location":x.location,"status":x.status,"created_at":x.created_at.isoformat()} for x in rows]}

@router.get("/directory/cases")
def paged_cases(limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),
                s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    q=select(m.Case).where(m.Case.school_id==ctx["sid"])
    total=s.scalar(select(func.count()).select_from(q.subquery()))
    rows=s.scalars(q.order_by(m.Case.id.desc()).offset(offset).limit(limit)).all()
    return {"total":total,"offset":offset,"limit":limit,"items":[{"id":x.id,"learner_id":x.learner_id,"title":x.title,"status":x.status} for x in rows]}

@router.get("/dashboard/aggregates")
def aggregates(s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    sid=ctx["sid"]
    learners=s.scalar(select(func.count()).select_from(m.Learner).where(m.Learner.school_id==sid))
    incidents=s.scalar(select(func.count()).select_from(m.Incident).where(m.Incident.school_id==sid))
    open_cases=s.scalar(select(func.count()).select_from(m.Case).where(m.Case.school_id==sid,m.Case.status!="closed"))
    locs=s.execute(select(m.Incident.location,func.count()).where(m.Incident.school_id==sid).group_by(m.Incident.location)).all()
    return {"school":ctx["school"],"learners":learners,"incidents":incidents,"open_cases":open_cases,"locations":dict(locs)}


@router.get("/reports/filtered")
def filtered_report(start:date|None=None,end:date|None=None,grade:str|None=None,
                    class_name:str|None=None,s:Session=Depends(m.db),
                    ctx=Depends(m.require(*MANAGERS))):
    if start and end and start>end:raise HTTPException(400,"End date precedes start date")
    query=select(m.Incident).join(m.Learner,
        (m.Learner.id==m.Incident.learner_id)&(m.Learner.school_id==m.Incident.school_id)).where(
        m.Incident.school_id==ctx["sid"])
    if start:query=query.where(m.Incident.created_at>=datetime.combine(start,time.min,tzinfo=timezone.utc))
    if end:query=query.where(m.Incident.created_at<datetime.combine(end+timedelta(days=1),time.min,tzinfo=timezone.utc))
    if grade:query=query.where(m.Learner.grade==grade)
    if class_name:query=query.where(m.Learner.class_name==class_name)
    sub=query.subquery()
    count=s.scalar(select(func.count()).select_from(sub))
    by_status=dict(s.execute(select(sub.c.status,func.count()).group_by(sub.c.status)).all())
    by_location=dict(s.execute(select(sub.c.location,func.count()).group_by(sub.c.location)).all())
    by_grade=dict(s.execute(select(m.Learner.grade,func.count()).join(
        sub,sub.c.learner_id==m.Learner.id).where(m.Learner.school_id==ctx["sid"]).group_by(m.Learner.grade)).all())
    return {"total":count,"by_status":by_status,"by_location":by_location,"by_grade":by_grade,
        "filters":{"start":str(start) if start else None,"end":str(end) if end else None,
            "grade":grade,"class_name":class_name}}
