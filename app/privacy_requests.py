"""School-scoped POPIA data-subject request intake and review tracker.

No automatic deletion or disclosure: school privacy staff must verify identity,
lawful basis and applicable record-retention obligations before fulfilment.
"""
from datetime import datetime,timezone,timedelta
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import String,Text,ForeignKey,DateTime,select
from sqlalchemy.orm import Mapped,mapped_column,Session
from app import main as m

router=APIRouter(prefix="/api/privacy")
class DataSubjectRequest(m.Base):
    __tablename__="data_subject_requests"
    id:Mapped[int]=mapped_column(primary_key=True)
    school_id:Mapped[int]=mapped_column(ForeignKey("schools.id"),index=True)
    learner_id:Mapped[int|None]=mapped_column(ForeignKey("learners.id"),nullable=True)
    request_type:Mapped[str]=mapped_column(String(40))
    requester_name:Mapped[str]=mapped_column(String(160))
    requester_contact:Mapped[str]=mapped_column(String(255))
    verification_status:Mapped[str]=mapped_column(String(30),default="unverified")
    status:Mapped[str]=mapped_column(String(30),default="received")
    notes:Mapped[str]=mapped_column(Text,default="")
    due_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

class Intake(BaseModel):
    learner_id:int|None=None
    request_type:str
    requester_name:str=Field(min_length=2,max_length=160)
    requester_contact:str=Field(min_length=5,max_length=255)
class Review(BaseModel):
    verification_status:str
    status:str
    notes:str=Field(default="",max_length=2000)

TYPES={"access","correction","objection","deletion_review","other"}
STATES={"received","under_review","awaiting_identity","awaiting_legal_review","fulfilled","declined"}
VERIFICATIONS={"unverified","verified","rejected"}

@router.post("/requests",status_code=201)
def intake(data:Intake,s:Session=Depends(m.db),ctx=Depends(m.require("school_admin","principal"))):
    if data.request_type not in TYPES:raise HTTPException(400,"Invalid request type")
    if data.learner_id is not None:
        learner=s.scalar(select(m.Learner).where(m.Learner.id==data.learner_id,m.Learner.school_id==ctx["sid"]))
        if not learner:raise HTTPException(404,"Learner not found")
    record=DataSubjectRequest(school_id=ctx["sid"],**data.model_dump(),
        due_at=datetime.now(timezone.utc)+timedelta(days=30))
    s.add(record);s.flush();m.log(s,ctx,"create","data_subject_request",record.id);s.commit()
    return {"id":record.id,"status":record.status,"note":"Identity review required; no data disclosed"}

@router.get("/requests")
def list_requests(s:Session=Depends(m.db),ctx=Depends(m.require("school_admin","principal"))):
    records=s.scalars(select(DataSubjectRequest).where(
        DataSubjectRequest.school_id==ctx["sid"]).order_by(DataSubjectRequest.id.desc()).limit(200)).all()
    return [{"id":x.id,"learner_id":x.learner_id,"request_type":x.request_type,
        "requester_name":x.requester_name,"requester_contact":x.requester_contact,
        "verification_status":x.verification_status,"status":x.status,
        "due_at":x.due_at.isoformat(),"notes":x.notes} for x in records]

@router.patch("/requests/{request_id}")
def review_request(request_id:int,data:Review,s:Session=Depends(m.db),ctx=Depends(m.require("school_admin","principal"))):
    if data.status not in STATES or data.verification_status not in VERIFICATIONS:
        raise HTTPException(400,"Invalid status")
    if data.status=="fulfilled" and data.verification_status!="verified":
        raise HTTPException(409,"Requester identity must be verified before fulfilment")
    record=s.scalar(select(DataSubjectRequest).where(
        DataSubjectRequest.id==request_id,DataSubjectRequest.school_id==ctx["sid"]))
    if not record:raise HTTPException(404,"Request not found")
    if record.status in ("fulfilled","declined") and data.status!=record.status:
        raise HTTPException(409,"Completed request requires a new review record")
    record.status=data.status;record.verification_status=data.verification_status;record.notes=data.notes
    m.log(s,ctx,"review","data_subject_request",record.id);s.commit()
    return {"ok":True,"status":record.status}
