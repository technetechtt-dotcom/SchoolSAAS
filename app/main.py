"""Multi-school discipline SaaS MVP; demonstration only, not production approved."""
from datetime import datetime, timezone, timedelta, date
from collections import Counter
import os, re, secrets, hashlib, hmac
import jwt
from argon2 import PasswordHasher
from fastapi import FastAPI, HTTPException, Depends, Response, Request, Cookie
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, String, ForeignKey, DateTime, Integer, Boolean, Text, Date, UniqueConstraint, select, func
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
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_secret: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
class Membership(Base):
    __tablename__ = 'memberships'
    __table_args__ = (UniqueConstraint('school_id','user_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    role: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    assigned_class: Mapped[str | None] = mapped_column(String(30), nullable=True)
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
    enrolled_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    grade_started: Mapped[str | None] = mapped_column(String(25), nullable=True)
class Offence(Base):
    __tablename__ = 'offences'
    __table_args__ = (UniqueConstraint('school_id','code'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(100))
    severity: Mapped[int] = mapped_column(Integer)
    escalate_hod: Mapped[bool] = mapped_column(Boolean, default=False)
    escalate_smt: Mapped[bool] = mapped_column(Boolean, default=False)
    repeat_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    similarity_group: Mapped[str | None] = mapped_column(String(80), nullable=True)
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
    review_status: Mapped[str] = mapped_column(String(30), default='pending')
    review_notes: Mapped[str] = mapped_column(Text, default='')
    flag_reason: Mapped[str] = mapped_column(String(80), default='')
    public_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
class Case(Base):
    __tablename__ = 'cases'
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey('learners.id'))
    title: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(40), default='open')
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    public_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
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
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
class Audit(Base):
    __tablename__ = 'audit_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(80))
    subject_type: Mapped[str] = mapped_column(String(50))
    subject_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class ActiveSession(Base):
    __tablename__ = 'active_sessions'
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class LoginFailure(Base):
    __tablename__ = 'login_failures'
    id: Mapped[int] = mapped_column(primary_key=True)
    identity_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class StaffInvite(Base):
    __tablename__ = 'staff_invites'
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    email: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30))
    assigned_class: Mapped[str | None] = mapped_column(String(30), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)

class ParentContact(Base):
    __tablename__ = 'parent_contacts'
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey('learners.id'))
    method: Mapped[str] = mapped_column(String(40))
    purpose: Mapped[str] = mapped_column(String(200))
    outcome: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class ReviewTask(Base):
    __tablename__ = 'review_tasks'
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey('incidents.id'))
    reason: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), default='open')
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class SchoolSetting(Base):
    __tablename__ = 'school_settings'
    __table_args__ = (UniqueConstraint('school_id','key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    key: Mapped[str] = mapped_column(String(60))
    value: Mapped[str] = mapped_column(String(200))

def _ensure_sqlite_columns():
    """Additive local upgrades for new nullable/defaulted columns (not a substitute for Alembic)."""
    if not str(engine.url).startswith('sqlite'):
        return
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    planned = {
        'users': [
            ('mfa_secret', 'VARCHAR(64)'),
            ('mfa_enabled', 'BOOLEAN DEFAULT 0'),
        ],
        'offences': [
            ('escalate_hod', 'BOOLEAN DEFAULT 0'),
            ('escalate_smt', 'BOOLEAN DEFAULT 0'),
            ('repeat_threshold', 'INTEGER'),
            ('similarity_group', 'VARCHAR(80)'),
        ],
        'incidents': [
            ('flag_reason', "VARCHAR(80) DEFAULT ''"),
            ('public_ref', 'VARCHAR(40)'),
        ],
        'cases': [
            ('public_ref', 'VARCHAR(40)'),
        ],
        'interventions': [
            ('due_at', 'DATETIME'),
        ],
        'learners': [
            ('enrolled_on', 'DATE'),
            ('grade_started', 'VARCHAR(25)'),
        ],
    }
    with engine.begin() as conn:
        for table, cols in planned.items():
            if table not in insp.get_table_names():
                continue
            present = {c['name'] for c in insp.get_columns(table)}
            for name, typ in cols:
                if name not in present:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {typ}'))

def _ensure_sqlite_user_mfa_columns():
    if not str(engine.url).startswith('sqlite'):
        return
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    if 'users' not in insp.get_table_names():
        return
    cols = {c['name'] for c in insp.get_columns('users')}
    with engine.begin() as conn:
        if 'mfa_secret' not in cols:
            conn.execute(text('ALTER TABLE users ADD COLUMN mfa_secret VARCHAR(64)'))
        if 'mfa_enabled' not in cols:
            conn.execute(text('ALTER TABLE users ADD COLUMN mfa_enabled BOOLEAN DEFAULT 0'))

@app.on_event('startup')
def startup():
    # Local prototype only; deployment must run Alembic with auto creation disabled.
    if os.getenv("SCHEMA_AUTO_CREATE","true").lower() == "true":
        import app.learner_journey  # noqa: F401 — register journey tables on Base.metadata
        Base.metadata.create_all(engine)
        _ensure_sqlite_user_mfa_columns()
        _ensure_sqlite_columns()

def db():
    with SessionLocal() as s: yield s

def issue_token(uid: int, school_id: int, session: Session):
    """Issue a revocable token; only a SHA-256 digest is stored server-side."""
    nonce = secrets.token_urlsafe(32)
    expiry = datetime.now(timezone.utc) + timedelta(hours=8)
    session.add(ActiveSession(token_hash=hashlib.sha256(nonce.encode()).hexdigest(),
                              user_id=uid, school_id=school_id, expires_at=expiry))
    return jwt.encode({'sub':str(uid), 'school_id':school_id,'jti':nonce,'exp':expiry},
                      JWT_SECRET, algorithm='HS256')

def revoke_token(raw: str | None, session: Session):
    if not raw:
        return
    try:
        payload = jwt.decode(raw, JWT_SECRET, algorithms=['HS256'])
        nonce = payload.get('jti','')
        stored = session.scalar(select(ActiveSession).where(
            ActiveSession.token_hash == hashlib.sha256(nonce.encode()).hexdigest()))
        if stored:
            session.delete(stored)
            session.commit()
    except jwt.InvalidTokenError:
        return

def login_identity(school_slug: str, email: str) -> str:
    raw = school_slug.strip().lower() + ':' + email.strip().lower()
    return hashlib.sha256(raw.encode()).hexdigest()

def check_login_limit(session: Session, identifier: str):
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    count = session.scalar(select(func.count()).select_from(LoginFailure).where(
        LoginFailure.identity_hash == identifier, LoginFailure.created_at >= cutoff))
    if count >= 5:
        raise HTTPException(429, 'Too many attempts. Try again after 15 minutes.')

def failed_login(session: Session, identifier: str):
    session.add(LoginFailure(identity_hash=identifier))
    session.commit()


def current(request: Request, session: Session=Depends(db)):
    token = request.cookies.get('session')
    if not token: raise HTTPException(401, 'Login required')
    try: payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256']); uid=int(payload['sub']); sid=int(payload['school_id']); nonce=payload['jti']
    except (jwt.InvalidTokenError, ValueError, KeyError): raise HTTPException(401, 'Invalid session')
    record=session.scalar(select(ActiveSession).where(ActiveSession.token_hash==hashlib.sha256(nonce.encode()).hexdigest(),ActiveSession.user_id==uid,ActiveSession.school_id==sid))
    if not record or record.expires_at.replace(tzinfo=timezone.utc)<=datetime.now(timezone.utc):
        raise HTTPException(401, 'Session expired or revoked')
    membership = session.scalar(select(Membership).where(Membership.user_id==uid, Membership.school_id==sid))
    school = session.get(School, sid)
    user=session.get(User,uid)
    if not membership or not membership.active or not user or not user.active or not school or school.status!='active': raise HTTPException(403, 'School access denied')
    assigned=[membership.assigned_class] if membership.assigned_class else []
    from app.operations import ClassAssignment
    assigned+=list(session.scalars(select(ClassAssignment.class_name).where(
        ClassAssignment.school_id==sid,ClassAssignment.user_id==uid)).all())
    return {'uid':uid,'sid':sid,'role':membership.role,'school':school.name,
            'assigned_class':membership.assigned_class,'assigned_classes':sorted(set(assigned))}

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
    admission_no: str=Field(default='', max_length=80)
    first_name: str=Field(min_length=1,max_length=120)
    surname: str=Field(min_length=1,max_length=120)
    grade: str=Field(min_length=1,max_length=25)
    class_name: str=Field(min_length=1,max_length=30)

def next_admission_candidate(used: set[str]) -> str:
    """Next school-scoped admission number from an in-memory used set (ADM-00001, ...)."""
    max_n = 0
    for adm in used:
        if not adm:
            continue
        if adm.upper().startswith('ADM-'):
            tail = adm.split('-', 1)[-1]
            if tail.isdigit():
                max_n = max(max_n, int(tail))
        elif str(adm).isdigit():
            max_n = max(max_n, int(adm))
    max_n = max(max_n, len(used))
    for _ in range(10000):
        max_n += 1
        candidate = f'ADM-{max_n:05d}'
        if candidate not in used:
            return candidate
    raise HTTPException(500, 'Could not allocate admission number')

def allocate_admission_no(s: Session, school_id: int) -> str:
    """Allocate the next school-scoped admission number from persisted learner records."""
    used = set(s.scalars(select(Learner.admission_no).where(Learner.school_id == school_id)).all())
    return next_admission_candidate(used)
class OffenceIn(BaseModel):
    code: str=Field(min_length=1,max_length=30)
    name: str=Field(min_length=1,max_length=160)
    category: str=Field(min_length=1,max_length=100)
    severity: int=Field(ge=1,le=4)
    escalate_hod: bool=False
    escalate_smt: bool=False
    repeat_threshold: int|None=Field(default=None,ge=1,le=20)
    similarity_group: str|None=Field(default=None,max_length=80)
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
    due_at: datetime|None=None

def setting_map(s:Session, school_id:int)->dict[str,str]:
    return {x.key:x.value for x in s.scalars(select(SchoolSetting).where(SchoolSetting.school_id==school_id)).all()}

def setting_int(settings:dict[str,str], key:str, default:int)->int:
    try:return int(settings.get(key, default))
    except (TypeError,ValueError):return default

def next_public_ref(s:Session, school_id:int, model, prefix:str, year:int)->str:
    n=s.scalar(select(func.count()).select_from(model).where(model.school_id==school_id)) or 0
    return f'{prefix}-{year}-{n+1:05d}'

def evaluate_repeat_flag(s:Session, school_id:int, learner_id:int, offence:Offence, settings:dict[str,str]):
    """Return (flagged, reason, similar_count, total_count). Never implies punishment."""
    window_days=setting_int(settings,'repeat_window_days',90)
    similar_threshold=offence.repeat_threshold if offence.repeat_threshold is not None else setting_int(settings,'repeat_similar_threshold',setting_int(settings,'repeat_threshold',3))
    total_threshold=setting_int(settings,'repeat_total_threshold',5)
    since=datetime.now(timezone.utc)-timedelta(days=window_days)
    recent=s.scalars(select(Incident).where(Incident.school_id==school_id,Incident.learner_id==learner_id,
        Incident.status!='withdrawn',Incident.created_at>=since)).all()
    total_count=len(recent)
    if offence.similarity_group:
        group_ids={o.id for o in s.scalars(select(Offence).where(Offence.school_id==school_id,Offence.similarity_group==offence.similarity_group)).all()}
        similar_count=sum(1 for i in recent if i.offence_id in group_ids)
    else:
        similar_count=sum(1 for i in recent if i.offence_id==offence.id)
    if getattr(offence,'escalate_smt',False) or offence.severity>=4:
        return True,'smt_review',similar_count,total_count
    if getattr(offence,'escalate_hod',False) or offence.severity>=3:
        return True,'serious_review',similar_count,total_count
    if similar_count>=similar_threshold:
        return True,'similar_repeat',similar_count,total_count
    if total_count>=total_threshold:
        return True,'total_repeat',similar_count,total_count
    return False,'',similar_count,total_count

@app.post('/api/register',status_code=201)
def register(data:Register, response:Response, s:Session=Depends(db)):
    if s.scalar(select(School).where(School.slug==data.slug)): raise HTTPException(409,'School slug already used')
    if s.scalar(select(User).where(User.email==data.email.lower())): raise HTTPException(409,'Email already registered; contact support to join another school')
    school=School(name=data.school_name,slug=data.slug); user=User(email=data.email.lower(),password_hash=ph.hash(data.password))
    s.add_all([school,user]); s.flush(); s.add(Membership(school_id=school.id,user_id=user.id,role='school_admin'))
    s.commit(); token=issue_token(user.id,school.id,s);s.commit()
    response.set_cookie('session',token,httponly=True,secure=os.getenv('COOKIE_SECURE','false')=='true',samesite='lax',max_age=28800)
    return {'school_id':school.id,'school':school.name,'role':'school_admin'}
@app.post('/api/login')
def login(data:Login,response:Response,s:Session=Depends(db)):
    slug = (data.school_slug or '').strip().lower()
    email = (data.email or '').strip().lower()
    identity = login_identity(slug, email)
    check_login_limit(s, identity)
    school=s.scalar(select(School).where(School.slug==slug))
    user=s.scalar(select(User).where(User.email==email))
    if not user or not school:
        failed_login(s, identity)
        raise HTTPException(401,'Invalid credentials')
    try:
        ph.verify(user.password_hash,data.password)
    except Exception:
        failed_login(s,identity)
        raise HTTPException(401,'Invalid credentials')
    mem=s.scalar(select(Membership).where(Membership.school_id==school.id,Membership.user_id==user.id))
    if not mem or not mem.active or not user.active or school.status!='active':
        raise HTTPException(403,'School access denied')
    s.query(LoginFailure).filter(LoginFailure.identity_hash==identity).delete(synchronize_session=False)
    s.commit()
    if getattr(user, 'mfa_enabled', False):
        from app.pilot_pack import issue_mfa_pending
        return {'mfa_required': True, 'mfa_token': issue_mfa_pending(user.id, school.id),
                'school': school.name, 'role': mem.role}
    token=issue_token(user.id,school.id,s)
    s.commit()
    response.set_cookie('session',token,httponly=True,secure=os.getenv('COOKIE_SECURE','false')=='true',samesite='lax',max_age=28800)
    return {'school':school.name,'role':mem.role,'mfa_required':False}
@app.post('/api/logout')
def logout(response:Response,request:Request,s:Session=Depends(db)):
    revoke_token(request.cookies.get('session'),s)
    response.delete_cookie('session')
    return {'ok':True}
@app.get('/api/me')
def me(request: Request, session: Session = Depends(db)):
    """UI session probe: return 200 + authenticated=false when signed out (avoids console 401 noise)."""
    token = request.cookies.get('session')
    if not token:
        return {'authenticated': False}
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        uid = int(payload['sub']); sid = int(payload['school_id']); nonce = payload['jti']
    except (jwt.InvalidTokenError, ValueError, KeyError):
        return {'authenticated': False}
    record = session.scalar(select(ActiveSession).where(
        ActiveSession.token_hash == hashlib.sha256(nonce.encode()).hexdigest(),
        ActiveSession.user_id == uid, ActiveSession.school_id == sid))
    if not record or record.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        return {'authenticated': False}
    membership = session.scalar(select(Membership).where(Membership.user_id == uid, Membership.school_id == sid))
    school = session.get(School, sid)
    user = session.get(User, uid)
    if not membership or not membership.active or not user or not user.active or not school or school.status != 'active':
        return {'authenticated': False}
    return {'authenticated': True, 'uid': uid, 'sid': sid, 'role': membership.role,
            'school': school.name, 'assigned_class': membership.assigned_class,
            'mfa_enabled': bool(getattr(user, 'mfa_enabled', False)),
            'platform_admin': user.email in {x.strip().lower() for x in os.getenv('PLATFORM_ADMIN_EMAILS','').split(',') if x.strip()}}
@app.get('/api/learners')
def learners(s:Session=Depends(db),ctx=Depends(current)):
    q=select(Learner).where(Learner.school_id==ctx['sid'])
    if ctx['role']=='educator':
        if not ctx['assigned_classes']:return []
        q=q.where(Learner.class_name.in_(ctx['assigned_classes']))
    return [dict(id=x.id,admission_no=x.admission_no,name=x.first_name+' '+x.surname,grade=x.grade,class_name=x.class_name) for x in s.scalars(q.order_by(Learner.surname).limit(500)).all()]
@app.post('/api/learners',status_code=201)
def add_learner(data:LearnerIn,s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    payload=data.model_dump()
    admission=(payload.get('admission_no') or '').strip()
    if admission:
        if s.scalar(select(Learner).where(Learner.school_id==ctx['sid'],Learner.admission_no==admission)):
            raise HTTPException(409,'Admission number exists')
    else:
        admission=allocate_admission_no(s, ctx['sid'])
    payload['admission_no']=admission
    item=Learner(school_id=ctx['sid'],**payload);s.add(item);s.flush();log(s,ctx,'create','learner',item.id);s.commit()
    return {'id':item.id,'admission_no':item.admission_no}
@app.get('/api/offences')
def offences(s:Session=Depends(db),ctx=Depends(current)):
    return [{'id':o.id,'code':o.code,'name':o.name,'category':o.category,'severity':o.severity,
             'escalate_hod':bool(getattr(o,'escalate_hod',False)),'escalate_smt':bool(getattr(o,'escalate_smt',False)),
             'repeat_threshold':o.repeat_threshold,'similarity_group':o.similarity_group or ''}
            for o in s.scalars(select(Offence).where(Offence.school_id==ctx['sid']).order_by(Offence.code)).all()]
@app.post('/api/offences',status_code=201)
def add_offence(data:OffenceIn,s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt'))):
    if s.scalar(select(Offence).where(Offence.school_id==ctx['sid'],Offence.code==data.code)): raise HTTPException(409,'Offence code exists')
    payload=data.model_dump();payload['similarity_group']=(payload.get('similarity_group') or None)
    o=Offence(school_id=ctx['sid'],**payload);s.add(o);s.flush();log(s,ctx,'create','offence',o.id);s.commit();return {'id':o.id}
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
    if ctx['role']=='educator' and learner.class_name not in ctx['assigned_classes']:raise HTTPException(403,'Learner is outside your assigned classes')
    settings=setting_map(s,ctx['sid'])
    year=setting_int(settings,'academic_year',datetime.now(timezone.utc).year)
    prefix=(settings.get('incident_prefix') or 'INC').strip() or 'INC'
    i=Incident(school_id=ctx['sid'],reporter_id=ctx['uid'],**data.model_dump())
    i.public_ref=next_public_ref(s,ctx['sid'],Incident,prefix,year)
    s.add(i);s.flush()
    flagged,reason,similar_count,total_count=evaluate_repeat_flag(s,ctx['sid'],i.learner_id,offence,settings)
    i.flag_reason=reason
    if flagged:
        labels={'similar_repeat':'Repeat review (similar behaviour)','total_repeat':'Repeat review (total incidents)',
                'serious_review':'Serious incident review','smt_review':'SMT review required'}
        s.add(ReviewTask(school_id=ctx['sid'],incident_id=i.id,reason=labels.get(reason,'Review required'),
                         due_at=datetime.now(timezone.utc)+timedelta(days=setting_int(settings,'follow_up_default_days',7))))
    log(s,ctx,'create','incident',i.id);s.commit()
    return {'id':i.id,'public_ref':i.public_ref,'same_offence_count':similar_count,'total_in_window':total_count,
            'flag_reason':reason,'requires_review':flagged,'message':'Review flag only; no automatic punishment'}
@app.post('/api/cases',status_code=201)
def add_case(data:CaseIn,s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    learner=s.scalar(select(Learner).where(Learner.id==data.learner_id,Learner.school_id==ctx['sid']))
    ids=set(data.incident_ids)
    matches=s.scalars(select(Incident).where(Incident.school_id==ctx['sid'],Incident.learner_id==data.learner_id,Incident.id.in_(ids))).all()
    if not learner or len(matches)!=len(ids):raise HTTPException(400,'Incidents must belong to the selected learner and school')
    settings=setting_map(s,ctx['sid'])
    year=setting_int(settings,'academic_year',datetime.now(timezone.utc).year)
    prefix=(settings.get('case_prefix') or 'CASE').strip() or 'CASE'
    case=Case(school_id=ctx['sid'],learner_id=data.learner_id,title=data.title,
              public_ref=next_public_ref(s,ctx['sid'],Case,prefix,year))
    s.add(case);s.flush()
    for i in matches:s.add(CaseIncident(school_id=ctx['sid'],case_id=case.id,incident_id=i.id))
    log(s,ctx,'create','case',case.id);s.commit();return {'id':case.id,'public_ref':case.public_ref}
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


# Phase 0.2: basic CSRF and role-scoped management workflows. Pilot-use only.
@app.middleware('http')
async def csrf_and_headers(request:Request,call_next):
    if request.method in ('POST','PUT','PATCH','DELETE') and request.url.path.startswith('/api/'):
        origin=request.headers.get('origin')
        if origin:
            from urllib.parse import urlsplit
            target=urlsplit(origin)
            if target.netloc!=request.headers.get('host') or target.scheme not in ('https','http'):
                return Response('Origin not allowed',status_code=403)
        if request.cookies.get('session') and request.url.path not in ('/api/register','/api/login'):
            c=request.cookies.get('csrf_token','')
            h=request.headers.get('x-csrf-token','')
            if not c or not h or not hmac.compare_digest(c,h):
                return Response('CSRF token required',status_code=403)
    resp=await call_next(request)
    if request.url.path.startswith('/api/') and not request.cookies.get('csrf_token'):
        resp.set_cookie('csrf_token',secrets.token_urlsafe(32),samesite='lax',
            secure=os.getenv('COOKIE_SECURE','false')=='true',httponly=False)
    resp.headers['X-Content-Type-Options']='nosniff'
    resp.headers['X-Frame-Options']='DENY'
    resp.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    return resp

class InviteRequest(BaseModel):
    email:str=Field(min_length=5,max_length=255)
    role:str
    assigned_class:str|None=None
class InviteAccept(BaseModel):
    token:str
    password:str=Field(min_length=12,max_length=128)
class MemberPatch(BaseModel):
    active:bool
    role:str
    assigned_class:str|None=None
class LearnerPatch(BaseModel):
    grade:str|None=None
    class_name:str|None=None
    active:bool|None=None
class ReviewPatch(BaseModel):
    status:str
    notes:str=Field(default='',max_length=2000)
class StatusPatch(BaseModel):
    status:str
class ContactInput(BaseModel):
    learner_id:int
    method:str=Field(min_length=1,max_length=40)
    purpose:str=Field(min_length=1,max_length=200)
    outcome:str=Field(min_length=1,max_length=200)
class RuleInput(BaseModel):
    repeat_threshold:int=Field(ge=2,le=10)
    repeat_window_days:int=Field(default=90,ge=7,le=365)
    repeat_similar_threshold:int=Field(default=3,ge=1,le=20)
    repeat_total_threshold:int=Field(default=5,ge=1,le=30)
    follow_up_default_days:int=Field(default=7,ge=1,le=60)
    incident_prefix:str=Field(default='INC',min_length=1,max_length=12)
    case_prefix:str=Field(default='CASE',min_length=1,max_length=12)
    admission_prefix:str=Field(default='ADM',min_length=1,max_length=12)

STAFF_ROLES={'school_admin','principal','smt','hod','educator'}

@app.get('/api/members')
def members(s:Session=Depends(db),ctx=Depends(require('school_admin','principal'))):
    q=select(Membership,User).join(User,Membership.user_id==User.id).where(Membership.school_id==ctx['sid'])
    return [{'id':m.id,'user_id':u.id,'email':u.email,'role':m.role,'active':m.active,'assigned_class':m.assigned_class} for m,u in s.execute(q).all()]

@app.post('/api/invitations',status_code=201)
def invite(data:InviteRequest,s:Session=Depends(db),ctx=Depends(require('school_admin','principal'))):
    if data.role not in STAFF_ROLES or (data.role=='school_admin' and ctx['role']!='school_admin'):
        raise HTTPException(400,'Role not permitted')
    token=secrets.token_urlsafe(32)
    i=StaffInvite(school_id=ctx['sid'],email=data.email.lower(),role=data.role,
        assigned_class=data.assigned_class,token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=datetime.now(timezone.utc)+timedelta(days=3))
    s.add(i);s.flush();log(s,ctx,'invite','staff_invite',i.id)
    emailed=False
    try:
        from app import mailer
        if mailer.smtp_ready():
            mailer.send_email(data.email.lower(),'SchoolCare staff invitation',
                f"You have been invited to join {ctx['school']} as {data.role}.\n\n"
                f"Accept in the app with this invitation token (expires in 72 hours):\n{token}\n\n"
                f"Open: {mailer.public_url()}\n")
            emailed=True
    except Exception:
        raise HTTPException(503,'Invitation email delivery failed')
    s.commit()
    out={'expires_in_hours':72,'emailed':emailed}
    if emailed:
        out['notice']='Invitation emailed to the staff member.'
    else:
        out['token']=token
        out['notice']='SMTP not configured; share this token with the intended staff member privately.'
    return out

@app.post('/api/invitations/accept',status_code=201)
def accept_invite(data:InviteAccept,s:Session=Depends(db)):
    digest=hashlib.sha256(data.token.encode()).hexdigest()
    inv=s.scalar(select(StaffInvite).where(StaffInvite.token_hash==digest))
    if not inv or inv.used or inv.expires_at.replace(tzinfo=timezone.utc)<datetime.now(timezone.utc):
        raise HTTPException(400,'Invalid or expired invitation')
    school=s.get(School,inv.school_id)
    if not school or school.status!='active':raise HTTPException(403,'School inactive')
    user=s.scalar(select(User).where(User.email==inv.email))
    if user:
        try:ph.verify(user.password_hash,data.password)
        except Exception:raise HTTPException(401,'Invalid existing-user password')
    else:
        user=User(email=inv.email,password_hash=ph.hash(data.password));s.add(user);s.flush()
    if s.scalar(select(Membership).where(Membership.school_id==inv.school_id,Membership.user_id==user.id)):
        raise HTTPException(409,'Already a member')
    s.add(Membership(school_id=inv.school_id,user_id=user.id,role=inv.role,assigned_class=inv.assigned_class))
    inv.used=True;s.commit();return {'school':school.name,'message':'Invitation accepted; sign in normally'}

@app.patch('/api/members/{member_id}')
def patch_member(member_id:int,data:MemberPatch,s:Session=Depends(db),ctx=Depends(require('school_admin','principal'))):
    m=s.scalar(select(Membership).where(Membership.id==member_id,Membership.school_id==ctx['sid']))
    if not m:raise HTTPException(404,'Member not found')
    if data.role not in STAFF_ROLES or (data.role=='school_admin' and ctx['role']!='school_admin'):
        raise HTTPException(400,'Role not permitted')
    if m.role=='school_admin' and ctx['role']!='school_admin':raise HTTPException(403,'Admin required')
    if m.user_id==ctx['uid'] and (not data.active or data.role!=m.role):raise HTTPException(400,'Cannot disable or demote self')
    m.active=data.active;m.role=data.role;m.assigned_class=data.assigned_class
    log(s,ctx,'update','membership',m.id);s.commit();return {'ok':True}

@app.patch('/api/learners/{learner_id}')
def patch_learner(learner_id:int,data:LearnerPatch,s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    x=s.scalar(select(Learner).where(Learner.id==learner_id,Learner.school_id==ctx['sid']))
    if not x:raise HTTPException(404,'Learner not found')
    for k,v in data.model_dump(exclude_none=True).items():setattr(x,k,v)
    log(s,ctx,'update','learner',x.id);s.commit();return {'ok':True}

@app.patch('/api/incidents/{incident_id}/review')
def patch_incident(incident_id:int,data:ReviewPatch,s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    if data.status not in ('pending','verified','disputed','referred','resolved','withdrawn'):
        raise HTTPException(400,'Invalid status')
    i=s.scalar(select(Incident).where(Incident.id==incident_id,Incident.school_id==ctx['sid']))
    if not i:raise HTTPException(404,'Incident not found')
    i.review_status=data.status;i.review_notes=data.notes
    if data.status in ('resolved','withdrawn'):i.status=data.status
    log(s,ctx,'review','incident',i.id);s.commit();return {'ok':True}

@app.patch('/api/cases/{case_id}')
def patch_case(case_id:int,data:StatusPatch,s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    if data.status not in ('open','monitoring','hod_review','smt_review','formal_process','awaiting_outcome','closed','reopened'):
        raise HTTPException(400,'Invalid status')
    c=s.scalar(select(Case).where(Case.id==case_id,Case.school_id==ctx['sid']))
    if not c:raise HTTPException(404,'Case not found')
    before=c.status
    if before == data.status:return {'ok':True}
    from app.operations import CaseEvent
    c.status=data.status
    s.add(CaseEvent(school_id=ctx['sid'],case_id=c.id,author_user_id=ctx['uid'],
                    kind='decision',note='Case status changed from '+before+' to '+data.status))
    log(s,ctx,'update','case',c.id);s.commit();return {'ok':True}

@app.get('/api/interventions')
def list_interventions(s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    return [{'id':i.id,'incident_id':i.incident_id,'type':i.type,'outcome':i.outcome,'notes':i.notes,
             'due_at':i.due_at.isoformat() if getattr(i,'due_at',None) else None}
        for i in s.scalars(select(Intervention).where(Intervention.school_id==ctx['sid']).limit(200)).all()]

@app.post('/api/parent-contacts',status_code=201)
def add_contact(data:ContactInput,s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    learner=s.scalar(select(Learner).where(Learner.id==data.learner_id,Learner.school_id==ctx['sid']))
    if not learner:raise HTTPException(404,'Learner not found')
    item=ParentContact(school_id=ctx['sid'],**data.model_dump());s.add(item);s.flush()
    log(s,ctx,'create','parent_contact',item.id);s.commit();return {'id':item.id}

@app.get('/api/parent-contacts')
def list_contacts(s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    return [{'id':x.id,'learner_id':x.learner_id,'method':x.method,'purpose':x.purpose,'outcome':x.outcome}
        for x in s.scalars(select(ParentContact).where(ParentContact.school_id==ctx['sid']).limit(200)).all()]

@app.get('/api/review-tasks')
def list_review_tasks(s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    return [{'id':x.id,'incident_id':x.incident_id,'reason':x.reason,'status':x.status,'due_at':x.due_at.isoformat()}
        for x in s.scalars(select(ReviewTask).where(ReviewTask.school_id==ctx['sid']).limit(200)).all()]

@app.patch('/api/review-tasks/{task_id}')
def patch_review_task(task_id:int,data:StatusPatch,s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    if data.status not in ('open','in_progress','completed','cancelled'):raise HTTPException(400,'Invalid status')
    task=s.scalar(select(ReviewTask).where(ReviewTask.id==task_id,ReviewTask.school_id==ctx['sid']))
    if not task:raise HTTPException(404,'Task not found')
    task.status=data.status;log(s,ctx,'update','review_task',task.id);s.commit();return {'ok':True}

@app.get('/api/settings')
def get_settings(s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt'))):
    conf=setting_map(s,ctx['sid'])
    similar=setting_int(conf,'repeat_similar_threshold',setting_int(conf,'repeat_threshold',3))
    return {'repeat_threshold':similar,'repeat_window_days':setting_int(conf,'repeat_window_days',90),
            'repeat_similar_threshold':similar,'repeat_total_threshold':setting_int(conf,'repeat_total_threshold',5),
            'follow_up_default_days':setting_int(conf,'follow_up_default_days',7),
            'incident_prefix':conf.get('incident_prefix','INC'),'case_prefix':conf.get('case_prefix','CASE'),
            'admission_prefix':conf.get('admission_prefix','ADM')}

@app.put('/api/settings')
def set_settings(data:RuleInput,s:Session=Depends(db),ctx=Depends(require('school_admin','principal'))):
    payload=data.model_dump()
    payload['repeat_threshold']=payload['repeat_similar_threshold']
    for key,value in payload.items():
        r=s.scalar(select(SchoolSetting).where(SchoolSetting.school_id==ctx['sid'],SchoolSetting.key==key))
        if not r:s.add(SchoolSetting(school_id=ctx['sid'],key=key,value=str(value)))
        else:r.value=str(value)
    log(s,ctx,'update','school_settings',ctx['sid']);s.commit();return {'ok':True}

@app.get('/api/reports/summary')
def reports(s:Session=Depends(db),ctx=Depends(require('school_admin','principal','smt','hod'))):
    sid=ctx['sid'];items=s.scalars(select(Incident).where(Incident.school_id==sid)).all()
    offence_names={o.id:o.name for o in s.scalars(select(Offence).where(Offence.school_id==sid)).all()}
    grades={l.id:l.grade for l in s.scalars(select(Learner).where(Learner.school_id==sid)).all()}
    return {'by_offence':dict(Counter(offence_names.get(i.offence_id,'Unknown') for i in items)),
        'by_grade':dict(Counter(grades.get(i.learner_id,'Unknown') for i in items)),
        'by_location':dict(Counter(i.location for i in items))}

# Register the v0.3 school-scoped workflow APIs and their database models.
from app.extended import router as extended_router
app.include_router(extended_router)
from app.operations import router as operations_router
app.include_router(operations_router)
from app.account_recovery import router as recovery_router
app.include_router(recovery_router)
from app.pilot_pack import router as pilot_router
app.include_router(pilot_router)
from app.learner_journey import router as journey_router
app.include_router(journey_router)
from app.intervention_recommend import router as recommend_router
app.include_router(recommend_router)

@app.delete('/api/audit/{event_id}')
def delete_audit_blocked(event_id: int):
    raise HTTPException(405, 'Audit events are append-only and cannot be deleted')
