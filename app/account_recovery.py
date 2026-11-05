"""Password recovery with hashed one-use tokens and configured SMTP delivery."""
from datetime import datetime,timezone,timedelta
import hashlib,secrets
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,Field
from sqlalchemy import String,ForeignKey,DateTime,Boolean,select,func,delete
from sqlalchemy.orm import Session,Mapped,mapped_column
from app import main as m
from app import mailer

router=APIRouter(prefix="/api/account-recovery")
class PasswordReset(m.Base):
    __tablename__="password_resets"
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id"),index=True)
    token_hash:Mapped[str]=mapped_column(String(64),unique=True,index=True)
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
    used:Mapped[bool]=mapped_column(Boolean,default=False)

class RequestReset(BaseModel):
    email:str=Field(min_length=5,max_length=255)
class CompleteReset(BaseModel):
    token:str=Field(min_length=32,max_length=200)
    password:str=Field(min_length=12,max_length=128)

@router.post("/request")
def request_reset(data:RequestReset,request:Request,s:Session=Depends(m.db)):
    m.check_auth_rate_limits(s, request)
    if not mailer.smtp_ready():
        raise HTTPException(503,"Password recovery email is not configured")
    generic={"message":"If this account exists, recovery instructions will be sent."}
    user=s.scalar(select(m.User).where(m.User.email==data.email.strip().lower()))
    if not user or not user.active:return generic
    hour_ago=datetime.now(timezone.utc)-timedelta(hours=1)
    recent=s.scalar(select(func.count()).select_from(PasswordReset).where(
        PasswordReset.user_id==user.id,PasswordReset.created_at>=hour_ago))
    if recent>=3:return generic
    token=secrets.token_urlsafe(40)
    item=PasswordReset(user_id=user.id,token_hash=hashlib.sha256(token.encode()).hexdigest(),
         expires_at=datetime.now(timezone.utc)+timedelta(minutes=20))
    body=("A password reset was requested for this SchoolCare account. "
          "If this was not you, ignore this message.\n\n"
          "Reset URL (expires in 20 minutes): "+
          mailer.public_url("/#reset="+token)+"\n")
    from app.mail_outbox import send_or_queue
    result=send_or_queue(s,user.email,"SchoolCare password reset",body)
    if not result.get("sent") and result.get("queued") and "not configured" in (result.get("notice") or ""):
        raise HTTPException(503,"Password recovery email is not configured")
    s.add(item);s.commit()
    return generic

@router.post("/complete")
def complete_reset(data:CompleteReset,s:Session=Depends(m.db)):
    digest=hashlib.sha256(data.token.encode()).hexdigest()
    item=s.scalar(select(PasswordReset).where(PasswordReset.token_hash==digest))
    if not item or item.used or item.expires_at.replace(tzinfo=timezone.utc)<=datetime.now(timezone.utc):
        raise HTTPException(400,"Reset token is invalid or expired")
    user=s.get(m.User,item.user_id)
    if not user or not user.active:raise HTTPException(400,"Reset token invalid")
    user.password_hash=m.ph.hash(data.password)
    item.used=True
    s.execute(delete(m.ActiveSession).where(m.ActiveSession.user_id==user.id))
    s.execute(delete(PasswordReset).where(PasswordReset.user_id==user.id,PasswordReset.id!=item.id))
    try:
        from app.account_security import record_security_event
        record_security_event(s,user.id,None,"password_reset_completed",
                              "Password changed via recovery link",email_user=True)
    except Exception:
        pass
    s.commit()
    return {"ok":True,"message":"Password changed. Sign in again."}
