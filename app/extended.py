"""Additional school-scoped workflows for the v0.3 usability release.

This module extends the original MVP without changing its existing routes.
Sensitive records remain school-scoped and require explicit permissions.
"""
from datetime import datetime, timezone
from collections import Counter
import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Response, Request, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, ForeignKey, DateTime, Text, select, func, or_
from sqlalchemy.orm import Mapped, mapped_column, Session
from app import main as m

router=APIRouter(prefix="/api")
MANAGERS=('school_admin','principal','smt','hod')
ADMIN=('school_admin','principal')

class Appeal(m.Base):
    __tablename__="appeals"
    id:Mapped[int]=mapped_column(primary_key=True)
    school_id:Mapped[int]=mapped_column(ForeignKey("schools.id"),index=True)
    case_id:Mapped[int]=mapped_column(ForeignKey("cases.id"))
    reason:Mapped[str]=mapped_column(Text)
    status:Mapped[str]=mapped_column(String(30),default="submitted")
    outcome:Mapped[str]=mapped_column(Text,default="")
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

class Appointment(m.Base):
    __tablename__="appointments"
    id:Mapped[int]=mapped_column(primary_key=True)
    school_id:Mapped[int]=mapped_column(ForeignKey("schools.id"),index=True)
    learner_id:Mapped[int]=mapped_column(ForeignKey("learners.id"))
    title:Mapped[str]=mapped_column(String(180))
    scheduled_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    status:Mapped[str]=mapped_column(String(30),default="scheduled")

class SchoolDocument(m.Base):
    __tablename__="school_documents"
    id:Mapped[int]=mapped_column(primary_key=True)
    school_id:Mapped[int]=mapped_column(ForeignKey("schools.id"),index=True)
    learner_id:Mapped[int]=mapped_column(ForeignKey("learners.id"))
    title:Mapped[str]=mapped_column(String(180))
    body:Mapped[str]=mapped_column(Text)
    document_type:Mapped[str]=mapped_column(String(40),default="letter")
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

class AppealIn(BaseModel):
    case_id:int
    reason:str=Field(min_length=5,max_length=3000)
class AppealUpdate(BaseModel):
    status:str
    outcome:str=Field(default="",max_length=3000)
class AppointmentIn(BaseModel):
    learner_id:int
    title:str=Field(min_length=3,max_length=180)
    scheduled_at:datetime
class AppointmentUpdate(BaseModel):
    status:str
class DocIn(BaseModel):
    learner_id:int
    title:str=Field(min_length=3,max_length=180)
    body:str=Field(min_length=1,max_length=10000)
    document_type:str=Field(default="letter",max_length=40)
class InterventionUpdate(BaseModel):
    outcome:str
    notes:str=Field(default="",max_length=2000)
class CaseAssign(BaseModel):
    assigned_user_id:int|None=None

def school_record(s,model,identifier,sid):
    x=s.scalar(select(model).where(model.id==identifier,model.school_id==sid))
    if not x:raise HTTPException(404,"Record not found at this school")
    return x

def learner_scope(s,identifier,ctx):
    x=school_record(s,m.Learner,identifier,ctx["sid"])
    if ctx["role"]=="educator" and x.class_name not in ctx["assigned_classes"]:
        raise HTTPException(403,"Not assigned to learner")
    return x

@router.get("/learners/{learner_id}")
def learner_detail(learner_id:int,s:Session=Depends(m.db),ctx=Depends(m.current)):
    l=learner_scope(s,learner_id,ctx)
    result={"id":l.id,"admission_no":l.admission_no,"first_name":l.first_name,
        "surname":l.surname,"grade":l.grade,"class_name":l.class_name,"active":l.active}
    if ctx["role"]!="educator":
        result["incidents"]=[{"id":i.id,"status":i.status,"location":i.location,"date":i.created_at.isoformat()}
            for i in s.scalars(select(m.Incident).where(m.Incident.school_id==ctx["sid"],m.Incident.learner_id==l.id).order_by(m.Incident.id.desc()).limit(50)).all()]
        result["cases"]=[{"id":c.id,"title":c.title,"status":c.status}
            for c in s.scalars(select(m.Case).where(m.Case.school_id==ctx["sid"],m.Case.learner_id==l.id)).all()]
    return result

@router.get("/incidents/{incident_id}")
def incident_detail(incident_id:int,s:Session=Depends(m.db),ctx=Depends(m.current)):
    i=school_record(s,m.Incident,incident_id,ctx["sid"])
    if ctx["role"]=="educator" and i.reporter_id!=ctx["uid"]:raise HTTPException(403,"Not authorised to view this incident")
    l=learner_scope(s,i.learner_id,ctx)
    o=school_record(s,m.Offence,i.offence_id,ctx["sid"])
    return {"id":i.id,"learner_id":l.id,"learner_name":l.first_name+" "+l.surname,
            "offence":o.name,"severity":o.severity,"description":i.description,
            "location":i.location,"immediate_action":i.immediate_action,
            "status":i.status,"review_status":i.review_status,"review_notes":i.review_notes,
            "created_at":i.created_at.isoformat()}

@router.get("/cases/{case_id}")
def case_detail(case_id:int,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    c=school_record(s,m.Case,case_id,ctx["sid"])
    linked=s.scalars(select(m.CaseIncident).where(m.CaseIncident.school_id==ctx["sid"],m.CaseIncident.case_id==c.id)).all()
    return {"id":c.id,"learner_id":c.learner_id,"title":c.title,
            "status":c.status,"assigned_user_id":c.assigned_user_id,
            "incident_ids":[x.incident_id for x in linked]}

@router.get("/case-assignees")
def eligible_assignees(s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    """Only minimal staff data needed for assigning a case, not full membership admin."""
    q=select(m.Membership,m.User).join(m.User,m.User.id==m.Membership.user_id).where(
        m.Membership.school_id==ctx["sid"],m.Membership.active==True,m.User.active==True,
        m.Membership.role.in_(("school_admin","principal","smt","hod")))
    return [{"user_id":user.id,"label":user.email,"role":member.role} for member,user in s.execute(q).all()]

@router.patch("/cases/{case_id}/assign")
def assign_case(case_id:int,data:CaseAssign,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    c=school_record(s,m.Case,case_id,ctx["sid"])
    if data.assigned_user_id is not None:
        membership=s.scalar(select(m.Membership).where(m.Membership.school_id==ctx["sid"],m.Membership.user_id==data.assigned_user_id,m.Membership.active==True))
        if not membership:raise HTTPException(400,"Assignee is not an active member of this school")
    old_assignee=c.assigned_user_id
    c.assigned_user_id=data.assigned_user_id
    if old_assignee != data.assigned_user_id:
        from app.operations import CaseEvent
        s.add(CaseEvent(school_id=ctx["sid"],case_id=c.id,author_user_id=ctx["uid"],
            kind="note",note="Assigned staff changed from "+str(old_assignee or "unassigned")+
            " to "+str(data.assigned_user_id or "unassigned")))
    m.log(s,ctx,"assign","case",c.id);s.commit()
    return {"ok":True}

@router.patch("/interventions/{intervention_id}")
def update_intervention(intervention_id:int,data:InterventionUpdate,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    x=school_record(s,m.Intervention,intervention_id,ctx["sid"])
    if data.outcome not in ("pending","improved","partially_improved","no_improvement","follow_up","closed"):
        raise HTTPException(400,"Invalid intervention outcome")
    x.outcome=data.outcome;x.notes=data.notes
    m.log(s,ctx,"update","intervention",x.id);s.commit()
    return {"ok":True}

@router.get("/classes")
def classes(s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    rows=s.execute(select(m.Learner.grade,m.Learner.class_name,func.count()).where(m.Learner.school_id==ctx["sid"],m.Learner.active==True).group_by(m.Learner.grade,m.Learner.class_name).order_by(m.Learner.grade,m.Learner.class_name)).all()
    return [{"grade":r[0],"class_name":r[1],"learners":r[2]} for r in rows]

@router.get("/reports/incidents.csv")
def incident_export(s:Session=Depends(m.db),ctx=Depends(m.require(*ADMIN))):
    rows=s.scalars(select(m.Incident).where(m.Incident.school_id==ctx["sid"]).order_by(m.Incident.id).limit(10000)).all()
    out=io.StringIO();w=csv.writer(out);w.writerow(["Incident ID","Learner ID","Offence ID","Location","Status","Created"])
    def safe_csv(value):
        text_value=str(value)
        # Spreadsheet applications may interpret leading formula characters as executable formulas.
        if text_value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
            return "'" + text_value
        return text_value
    for x in rows:w.writerow([safe_csv(v) for v in (x.id,x.learner_id,x.offence_id,x.location,x.status,x.created_at.isoformat())])
    m.log(s,ctx,"export","incidents",0);s.commit()
    return Response(content=out.getvalue(),media_type="text/csv",headers={"Content-Disposition":'attachment; filename="school-incidents.csv"',"Cache-Control":"no-store"})

@router.get("/notifications")
def notifications(s:Session=Depends(m.db),ctx=Depends(m.current)):
    if ctx["role"]=="educator":
        return []
    rows=s.scalars(select(m.ReviewTask).where(m.ReviewTask.school_id==ctx["sid"],m.ReviewTask.status.in_(("open","in_progress"))).order_by(m.ReviewTask.due_at).limit(30)).all()
    return [{"id":x.id,"title":x.reason,"incident_id":x.incident_id,"due_at":x.due_at.isoformat(),"status":x.status} for x in rows]

@router.get("/appeals")
def appeals(s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    rows=s.scalars(select(Appeal).where(Appeal.school_id==ctx["sid"]).order_by(Appeal.id.desc()).limit(200)).all()
    return [{"id":x.id,"case_id":x.case_id,"reason":x.reason,"status":x.status,"outcome":x.outcome} for x in rows]

@router.post("/appeals",status_code=201)
def add_appeal(data:AppealIn,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    school_record(s,m.Case,data.case_id,ctx["sid"])
    x=Appeal(school_id=ctx["sid"],**data.model_dump());s.add(x);s.flush()
    m.log(s,ctx,"create","appeal",x.id);s.commit();return {"id":x.id}

@router.patch("/appeals/{appeal_id}")
def review_appeal(appeal_id:int,data:AppealUpdate,s:Session=Depends(m.db),ctx=Depends(m.require("school_admin","principal","smt"))):
    if data.status not in ("submitted","under_review","resolved","rejected"):raise HTTPException(400,"Invalid appeal status")
    x=school_record(s,Appeal,appeal_id,ctx["sid"]);x.status=data.status;x.outcome=data.outcome
    m.log(s,ctx,"review","appeal",x.id);s.commit();return {"ok":True}

@router.get("/appointments")
def appointments(s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    rows=s.scalars(select(Appointment).where(Appointment.school_id==ctx["sid"]).order_by(Appointment.scheduled_at.desc()).limit(200)).all()
    return [{"id":x.id,"learner_id":x.learner_id,"title":x.title,"scheduled_at":x.scheduled_at.isoformat(),"status":x.status} for x in rows]

@router.post("/appointments",status_code=201)
def add_appointment(data:AppointmentIn,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    school_record(s,m.Learner,data.learner_id,ctx["sid"])
    x=Appointment(school_id=ctx["sid"],**data.model_dump());s.add(x);s.flush()
    m.log(s,ctx,"create","appointment",x.id);s.commit();return {"id":x.id}

@router.patch("/appointments/{appointment_id}")
def update_appointment(appointment_id:int,data:AppointmentUpdate,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    if data.status not in ("scheduled","completed","cancelled"):raise HTTPException(400,"Invalid appointment status")
    x=school_record(s,Appointment,appointment_id,ctx["sid"]);x.status=data.status
    m.log(s,ctx,"update","appointment",x.id);s.commit();return {"ok":True}

@router.get("/documents")
def documents(s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    rows=s.scalars(select(SchoolDocument).where(SchoolDocument.school_id==ctx["sid"]).order_by(SchoolDocument.id.desc()).limit(200)).all()
    return [{"id":x.id,"learner_id":x.learner_id,"title":x.title,"document_type":x.document_type,"created_at":x.created_at.isoformat()} for x in rows]

@router.get("/documents/{document_id}")
def get_document(document_id:int,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    x=school_record(s,SchoolDocument,document_id,ctx["sid"])
    return {"id":x.id,"learner_id":x.learner_id,"title":x.title,"body":x.body,"document_type":x.document_type}

@router.post("/documents",status_code=201)
def add_document(data:DocIn,s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    school_record(s,m.Learner,data.learner_id,ctx["sid"])
    x=SchoolDocument(school_id=ctx["sid"],**data.model_dump());s.add(x);s.flush()
    m.log(s,ctx,"create","document",x.id);s.commit();return {"id":x.id}

@router.get("/subscription")
def subscription(ctx=Depends(m.require(*ADMIN)),s:Session=Depends(m.db)):
    school=s.get(m.School,ctx["sid"])
    if not school:raise HTTPException(404,"School not found")
    return {"plan":school.plan,"status":school.status,"billing_enabled":False,
            "message":"Billing not configured. No payments are collected."}


class SchoolSwitch(BaseModel):
    school_id:int

@router.get("/directory/learners")
def learner_directory(q:str="",grade:str="",limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),
                      s:Session=Depends(m.db),ctx=Depends(m.current)):
    query=select(m.Learner).where(m.Learner.school_id==ctx["sid"])
    if ctx["role"]=="educator":
        if not ctx["assigned_classes"]:return {"items":[],"total":0,"limit":limit,"offset":offset,"grade":grade,"grades":[]}
        query=query.where(m.Learner.class_name.in_(ctx["assigned_classes"]))
    grade_filter=(grade or "").strip()
    if grade_filter:
        # Accept "7", "Grade 7", "grade 7"
        normalized=grade_filter.lower().replace("grade","").strip()
        query=query.where(or_(m.Learner.grade==normalized,m.Learner.grade==grade_filter,
                              m.Learner.grade.ilike("grade "+normalized),m.Learner.grade.ilike(normalized)))
    if q.strip():
        term="%"+q.strip().replace("%",r"\%").replace("_",r"\_")+"%"
        query=query.where(or_(m.Learner.first_name.ilike(term),m.Learner.surname.ilike(term),
            m.Learner.admission_no.ilike(term),m.Learner.class_name.ilike(term),m.Learner.grade.ilike(term)))
    total=s.scalar(select(func.count()).select_from(query.subquery()))
    rows=s.scalars(query.order_by(m.Learner.grade,m.Learner.surname,m.Learner.id).offset(offset).limit(limit)).all()
    grade_rows=s.execute(select(m.Learner.grade,func.count()).where(m.Learner.school_id==ctx["sid"],m.Learner.active==True)
                         .group_by(m.Learner.grade).order_by(m.Learner.grade)).all()
    if ctx["role"]=="educator" and ctx["assigned_classes"]:
        grade_rows=s.execute(select(m.Learner.grade,func.count()).where(
            m.Learner.school_id==ctx["sid"],m.Learner.active==True,
            m.Learner.class_name.in_(ctx["assigned_classes"])).group_by(m.Learner.grade).order_by(m.Learner.grade)).all()
    return {"items":[{"id":x.id,"name":x.first_name+" "+x.surname,"admission_no":x.admission_no,
            "grade":x.grade,"class_name":x.class_name} for x in rows],
            "total":total,"limit":limit,"offset":offset,"grade":grade_filter,
            "grades":[{"grade":g,"learners":n} for g,n in grade_rows]}

@router.get("/mine/schools")
def my_schools(s:Session=Depends(m.db),ctx=Depends(m.current)):
    rows=s.execute(select(m.Membership,m.School).join(m.School,m.Membership.school_id==m.School.id)
        .where(m.Membership.user_id==ctx["uid"],m.Membership.active==True,m.School.status=="active")).all()
    return [{"id":sch.id,"name":sch.name,"role":mem.role,"current":sch.id==ctx["sid"]} for mem,sch in rows]

@router.post("/mine/schools/switch")
def switch_school(data:SchoolSwitch,response:Response,request:Request,s:Session=Depends(m.db),ctx=Depends(m.current)):
    membership=s.scalar(select(m.Membership).where(m.Membership.school_id==data.school_id,
        m.Membership.user_id==ctx["uid"],m.Membership.active==True))
    school=s.get(m.School,data.school_id)
    if not membership or not school or school.status!="active":raise HTTPException(403,"School access denied")
    new_token=m.issue_token(ctx["uid"],school.id,s)
    s.commit()
    m.revoke_token(request.cookies.get("session"),s)
    response.set_cookie("session",new_token,httponly=True,
        secure=m.os.getenv("COOKIE_SECURE","false")=="true",samesite="lax",max_age=28800)
    return {"school":school.name,"role":membership.role}


@router.get("/analytics/overview")
def analytics(s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    sid=ctx["sid"]
    items=s.scalars(select(m.Incident).where(m.Incident.school_id==sid)).all()
    offences={o.id:o for o in s.scalars(select(m.Offence).where(m.Offence.school_id==sid)).all()}
    severity=Counter(str(offences[i.offence_id].severity) for i in items if i.offence_id in offences)
    month=Counter(i.created_at.strftime("%Y-%m") for i in items)
    involved=len({i.learner_id for i in items})
    repeat_pairs=Counter((i.learner_id,i.offence_id) for i in items)
    repeat_learners=len({learner for (learner,offence),n in repeat_pairs.items() if n>=2})
    interventions=s.scalars(select(m.Intervention).where(m.Intervention.school_id==sid)).all()
    outstanding=s.scalar(select(func.count()).select_from(m.ReviewTask).where(
        m.ReviewTask.school_id==sid,m.ReviewTask.status.in_(("open","in_progress"))))
    return {"severity":dict(severity),"months":dict(sorted(month.items())),"learners_with_incidents":involved,
        "repeat_learners":repeat_learners,"repeat_rate":round(100*repeat_learners/involved,1) if involved else 0,
        "interventions":len(interventions),
        "completed_interventions":sum(x.outcome in ("improved","partially_improved","closed") for x in interventions),
        "pending_reviews":outstanding}


class BulkLearnerRow(BaseModel):
    admission_no:str=Field(default="",max_length=80)
    first_name:str=Field(min_length=1,max_length=120)
    surname:str=Field(min_length=1,max_length=120)
    grade:str=Field(min_length=1,max_length=25)
    class_name:str=Field(min_length=1,max_length=30)

class BulkLearnerIn(BaseModel):
    rows:list[BulkLearnerRow]=Field(min_length=1,max_length=1000)

@router.post("/learners/import",status_code=201)
def bulk_import_learners(data:BulkLearnerIn,s:Session=Depends(m.db),ctx=Depends(m.require(*ADMIN))):
    existing=set(s.scalars(select(m.Learner.admission_no).where(m.Learner.school_id==ctx["sid"])).all())
    created=0;skipped=[];assigned=[]
    for idx,row in enumerate(data.rows,1):
        admission=(row.admission_no or "").strip()
        if admission:
            if admission in existing:
                skipped.append({"row":idx,"admission_no":admission,"reason":"Duplicate admission number"})
                continue
        else:
            admission=m.next_admission_candidate(existing)
        existing.add(admission)
        s.add(m.Learner(school_id=ctx["sid"],admission_no=admission,
            first_name=row.first_name.strip(),surname=row.surname.strip(),
            grade=row.grade.strip(),class_name=row.class_name.strip()))
        assigned.append(admission);created+=1
    m.log(s,ctx,"bulk_import","learners",created)
    s.commit()
    return {"created":created,"skipped":skipped,"submitted":len(data.rows),"admission_numbers":assigned}

class AcademicSettings(BaseModel):
    academic_year:int=Field(ge=2020,le=2100)
    term:int=Field(ge=1,le=4)
    school_contact_email:str=Field(default="",max_length=200)

@router.get("/settings/academic")
def get_academic_settings(s:Session=Depends(m.db),ctx=Depends(m.require(*MANAGERS))):
    settings={x.key:x.value for x in s.scalars(select(m.SchoolSetting).where(
        m.SchoolSetting.school_id==ctx["sid"],m.SchoolSetting.key.in_(("academic_year","term","school_contact_email")))).all()}
    return {"academic_year":int(settings.get("academic_year",datetime.now(timezone.utc).year)),
            "term":int(settings.get("term","1")),
            "school_contact_email":settings.get("school_contact_email","")}

@router.put("/settings/academic")
def update_academic_settings(data:AcademicSettings,s:Session=Depends(m.db),ctx=Depends(m.require(*ADMIN))):
    for key,value in data.model_dump().items():
        setting=s.scalar(select(m.SchoolSetting).where(m.SchoolSetting.school_id==ctx["sid"],m.SchoolSetting.key==key))
        if not setting:s.add(m.SchoolSetting(school_id=ctx["sid"],key=key,value=str(value)))
        else:setting.value=str(value)
    m.log(s,ctx,"update","academic_settings",ctx["sid"]);s.commit()
    return {"ok":True}


class OffencePatch(BaseModel):
    name:str=Field(min_length=1,max_length=160)
    category:str=Field(min_length=1,max_length=100)
    severity:int=Field(ge=1,le=4)

@router.patch("/offences/{offence_id}")
def update_offence(offence_id:int,data:OffencePatch,s:Session=Depends(m.db),
                   ctx=Depends(m.require("school_admin","principal","smt"))):
    offence=school_record(s,m.Offence,offence_id,ctx["sid"])
    referenced=s.scalar(select(func.count()).select_from(m.Incident).where(
        m.Incident.school_id==ctx["sid"],m.Incident.offence_id==offence.id))
    if referenced:raise HTTPException(409,"This offence is referenced by incidents. Create a new version/code instead.")
    offence.name=data.name;offence.category=data.category;offence.severity=data.severity
    m.log(s,ctx,"update","offence",offence.id);s.commit()
    return {"ok":True}
