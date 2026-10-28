"""Multi-school discipline SaaS MVP; demonstration only, not production approved."""
from datetime import datetime, timezone, timedelta
from collections import Counter
import os, re, secrets
import jwt
from argon2 import PasswordHasher
from fastapi import FastAPI, HTTPException, Depends, Response, Request, Cookie
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, String, ForeignKey, DateTime, Integer, Boolean, Text, UniqueConstraint, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session
from pydantic import BaseModel, Field

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./schoolcare_demo.db')
JWT_SECRET = os.getenv('JWT_SECRET')
if not JWT_SECRET:
    raise RuntimeError('Set JWT_SECRET using .env; never use an embedded default')
engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {})
SessionLocal = sessionmaker(engine, expire_on_commit=False)
ph = PasswordHasher()
app = FastAPI(title='SchoolCare SaaS — Multi-school discipline platform', version='0.1.0')

class Base(DeclarativeBase): pass
class School(Base):
    __tablename__ = 'schools'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(30), default='trial')
    status: Mapped[str] = mapped_column(String(30), default='active')
class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(250))
class Membership(Base):
    __tablename__ = 'memberships'
    __table_args__ = (UniqueConstraint('school_id','user_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    role: Mapped[str] = mapped_column(String(30))
class Learner(Base):
    __tablename__ = 'learners'
    __table_args__ = (UniqueConstraint('school_id','admission_no'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    admission_no: Mapped[str] = mapped_column(String(80))
    first_name: Mapped[str] = mapped_column(String(120))
    surname: Mapped[str] = mapped_column(String(120))
    grade: Mapped[str] = mapped_column(String(25))
    class_name: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
class Offence(Base):
    __tablename__ = 'offences'
    __table_args__ = (UniqueConstraint('school_id','code'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(100))
    severity: Mapped[int] = mapped_column(Integer)
class Incident(Base):
    __tablename__ = 'incidents'
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey('learners.id'))
    offence_id: Mapped[int] = mapped_column(ForeignKey('offences.id'))
    reporter_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    location: Mapped[str] = mapped_column(String(90))
    description: Mapped[str] = mapped_column(Text)
    immediate_action: Mapped[str] = mapped_column(String(140))
    status: Mapped[str] = mapped_column(String(40), default='reported')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
class Case(Base):
    __tablename__ = 'cases'
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey('learners.id'))
    title: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(40), default='open')
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
class CaseIncident(Base):
    __tablename__ = 'case_incidents'
    __table_args__ = (UniqueConstraint('school_id','case_id','incident_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey('cases.id'))
    incident_id: Mapped[int] = mapped_column(ForeignKey('incidents.id'))
class Intervention(Base):
    __tablename__ = 'interventions'
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey('incidents.id'))
    type: Mapped[str] = mapped_column(String(120))
    notes: Mapped[str] = mapped_column(Text, default='')
    owner_user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    outcome: Mapped[str] = mapped_column(String(50), default='pending')
class Audit(Base):
    __tablename__ = 'audit_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(80))
    subject_type: Mapped[str] = mapped_column(String(50))
    subject_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

@app.on_event('startup')
def startup(): Base.metadata.create_all(engine)  # replace with Alembic migrations before deployment

def db():
    with SessionLocal() as s: yield s

def issue_token(uid: int, school_id: int):
    return jwt.encode({'sub':str(uid),'school_id':school_id,'exp':datetime.now(timezone.utc)+timedelta(hours=8)}, JWT_SECRET, algorithm='HS256')

def current(request: Request, session: Session=Depends(db)):
    token = request.cookies.get('session')
    if not token: raise HTTPException(401, 'Login required')
    try: payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256']); uid=int(payload['sub']); sid=int(payload['school_id'])
    except (jwt.InvalidTokenError, ValueError, KeyError): raise HTTPException(401, 'Invalid session')
    membership = session.scalar(select(Membership).where(Membership.user_id==uid, Membership.school_id==sid))
    school = session.get(School, sid)
    if not membership or not school or school.status!='active': raise HTTPException(403, 'School access denied')
    return {'uid':uid,'sid':sid,'role':membership.role,'school':school.name}

def require(*roles):
    def dependency(ctx=Depends(current)):
        if ctx['role'] not in roles: raise HTTPException(403, 'Insufficient permissions')
        return ctx
    return dependency

def log(s, ctx, action, typ, ident): s.add(Audit(school_id=ctx['sid'],user_id=ctx['uid'],action=action,subject_type=typ,subject_id=ident))

class Register(BaseModel):
    school_name: str = Field(min_length=3, max_length=200)
    slug: str = Field(pattern=r'^[a-z0-9-]{3,40}$')
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=12, max_length=128)
class Login(BaseModel):
    email: str
    password: str
    school_slug: str
class LearnerIn(BaseModel):
    admission_no: str=Field(min_length=1,max_length=80)
    first_name: str=Field(min_length=1,max_length=120)
    surname: str=Field(min_length=1,max_length=120)
    grade: str=Field(min_length=1,max_length=25)
    class_name: str=Field(min_length=1,max_length=30)
class OffenceIn(BaseModel):
    code: str=Field(min_length=1,max_length=30)
    name: str=Field(min_length=1,max_length=160)
    category: str=Field(min_length=1,max_length=100)
    severity: int=Field(ge=1,le=4)
class IncidentIn(BaseModel):
    learner_id: int
    offence_id: int
    location: str=Field(min_length=1,max_length=90)
    description: str=Field(min_length=1,max_length=2000)
    immediate_action: str=Field(min_length=1,max_length=140)
class CaseIn(BaseModel):
    learner_id: int
    title: str=Field(min_length=1,max_length=180)
    incident_ids: list[int]=Field(min_length=1)
class InterventionIn(BaseModel):
    incident_id: int
    type: str=Field(min_length=1,max_length=120)
    notes: str=Field(default='',max_length=2000)

@app.post('/api/register',status_code=201)
def register(data:Register, response:Response, s:Session=Depends(db)):
    if s.scalar(select(School).where(School.slug==data.slug)): raise HTTPException(409,'School slug already used')
    if s.scalar(select(User).where(User.email==data.email.lower())): raise HTTPException(409,'Email already registered; contact support to join another school')
    school=School(name=data.school_name,slug=data.slug); user=User(email=data.email.lower(),password_hash=ph.hash(data.password))
    s.add_all([school,user]); s.flush(); s.add(Membership(school_id=school.id,user_id=user.id,role='school_admin'))
    s.commit(); response.set_cookie('session',issue_token(user.id,school.id),httponly=True,secure=os.getenv('COOKIE_SECURE','false')=='true',samesite='lax',max_age=28800)
    return {'school_id':school.id,'school':school.name,'role':'school_admin'}
@app.post('/api/login')
def login(data:Login,response:Response,s:Session=Depends(db)):
    school=s.scalar(select(School).where(School.slug==data.school_slug))
    user=s.scalar(select(User).where(User.email==data.email.lower()))
    if not user or not school: raise HTTPException(401,'Invalid credentials')
    try: ph.verify(user.password_hash,data.password)
    except Exception: raise HTTPException(401,'Invalid credentials')
    mem=s.scalar(select(Membership).where(Membership.school_id==school.id,Membership.user_id==user.id))
    if not mem or school.status!='active': raise HTTPException(403,'School access denied')
    response.set_cookie('session',issue_token(user.id,school.id),httponly=True,secure=os.getenv('COOKIE_SECURE','false')=='true',samesite='lax',max_age=28800)
    return {'school':school.name,'role':mem.role}
@app.post('/api/logout')
def logout(response:Response): response.delete_cookie('session'); return {'ok':True}
@app.get('/api/me')
def me(ctx=Depends(current)): return ctx
@app.get('/api/learners')
def learners(s:Session=Depends(db),ctx=Depends(current)):
    return [dict(id=x.id,admission_no=x.admission_no,name=x.first_name+' '+x.surname,grade=x.grade,class_name=x.class_name) for x in s.scalars(select(Learner).where(Learner.school_id==ctx['sid']).order_by(Learner.surname)).all()]
@app.post('/api/learners',status_code=201)
def add_learner(data:LearnerIn,s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    if s.scalar(select(Learner).where(Learner.school_id==ctx['sid'],Learner.admission_no==data.admission_no)): raise HTTPException(409,'Admission number exists')
    item=Learner(school_id=ctx['sid'],**data.model_dump());s.add(item);s.flush();log(s,ctx,'create','learner',item.id);s.commit();return {'id':item.id}
@app.get('/api/offences')
def offences(s:Session=Depends(db),ctx=Depends(current)):
    return [{'id':o.id,'code':o.code,'name':o.name,'category':o.category,'severity':o.severity} for o in s.scalars(select(Offence).where(Offence.school_id==ctx['sid']).order_by(Offence.code)).all()]
@app.post('/api/offences',status_code=201)
def add_offence(data:OffenceIn,s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt'))):
    if s.scalar(select(Offence).where(Offence.school_id==ctx['sid'],Offence.code==data.code)): raise HTTPException(409,'Offence code exists')
    o=Offence(school_id=ctx['sid'],**data.model_dump());s.add(o);s.flush();log(s,ctx,'create','offence',o.id);s.commit();return {'id':o.id}
@app.get('/api/incidents')
def incidents(s:Session=Depends(db),ctx=Depends(current)):
    q=select(Incident).where(Incident.school_id==ctx['sid']).order_by(Incident.id.desc())
    if ctx['role']=='educator': q=q.where(Incident.reporter_id==ctx['uid'])
    return [dict(id=i.id,learner_id=i.learner_id,offence_id=i.offence_id,location=i.location,description=i.description,status=i.status,created_at=i.created_at.isoformat()) for i in s.scalars(q).all()]
@app.post('/api/incidents',status_code=201)
def add_incident(data:IncidentIn,s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod','educator'))):
    learner=s.scalar(select(Learner).where(Learner.id==data.learner_id,Learner.school_id==ctx['sid']))
    offence=s.scalar(select(Offence).where(Offence.id==data.offence_id,Offence.school_id==ctx['sid']))
    if not learner or not offence: raise HTTPException(404,'Learner or offence not found at this school')
    i=Incident(school_id=ctx['sid'],reporter_id=ctx['uid'],**data.model_dump());s.add(i);s.flush()
    same=s.scalar(select(func.count()).select_from(Incident).where(Incident.school_id==ctx['sid'],Incident.learner_id==i.learner_id,Incident.offence_id==i.offence_id,Incident.status!='withdrawn'))
    log(s,ctx,'create','incident',i.id);s.commit()
    return {'id':i.id,'same_offence_count':same,'requires_review':same>=3 or offence.severity>=3,'message':'Review flag only; no automatic punishment'}
@app.post('/api/cases',status_code=201)
def add_case(data:CaseIn,s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    learner=s.scalar(select(Learner).where(Learner.id==data.learner_id,Learner.school_id==ctx['sid']))
    ids=set(data.incident_ids)
    matches=s.scalars(select(Incident).where(Incident.school_id==ctx['sid'],Incident.learner_id==data.learner_id,Incident.id.in_(ids))).all()
    if not learner or len(matches)!=len(ids):raise HTTPException(400,'Incidents must belong to the selected learner and school')
    case=Case(school_id=ctx['sid'],learner_id=data.learner_id,title=data.title);s.add(case);s.flush()
    for i in matches:s.add(CaseIncident(school_id=ctx['sid'],case_id=case.id,incident_id=i.id))
    log(s,ctx,'create','case',case.id);s.commit();return {'id':case.id}
@app.get('/api/cases')
def cases(s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    return [{'id':c.id,'learner_id':c.learner_id,'title':c.title,'status':c.status} for c in s.scalars(select(Case).where(Case.school_id==ctx['sid'])).all()]
@app.post('/api/interventions',status_code=201)
def add_intervention(data:InterventionIn,s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    inc=s.scalar(select(Incident).where(Incident.id==data.incident_id,Incident.school_id==ctx['sid']))
    if not inc:raise HTTPException(404,'Incident not found')
    x=Intervention(school_id=ctx['sid'],owner_user_id=ctx['uid'],**data.model_dump());s.add(x);s.flush();log(s,ctx,'create','intervention',x.id);s.commit();return {'id':x.id}
@app.get('/api/dashboard')
def dashboard(s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    sid=ctx['sid']; incidents=s.scalars(select(Incident).where(Incident.school_id==sid)).all()
    return {'school':ctx['school'],'learners':s.scalar(select(func.count()).select_from(Learner).where(Learner.school_id==sid)),'incidents':len(incidents),'open_cases':s.scalar(select(func.count()).select_from(Case).where(Case.school_id==sid,Case.status!='closed')),'locations':dict(Counter(i.location for i in incidents))}
@app.get('/api/audit')
def audit(s:Session=Depends(db),ctx=Depends(require('school_admin','principal'))):
    return [{'action':a.action,'subject':a.subject_type,'subject_id':a.subject_id,'at':a.created_at.isoformat()} for a in s.scalars(select(Audit).where(Audit.school_id==ctx['sid']).order_by(Audit.id.desc()).limit(100)).all()]
@app.get('/')
def home():return FileResponse('app/index.html')
