"""Staff reminder queue remains tenant-scoped and duplicate-resistant on repeat runs."""
import os
from datetime import datetime,timezone,timedelta
os.environ.setdefault("JWT_SECRET","reminder-testing-secret")
os.environ["DATABASE_URL"]="sqlite://"
from sqlalchemy import create_engine,select,func
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app import main,operations
from app.mail_outbox import EmailOutbox

def test_reminder_queue_avoids_repeats_and_learner_details():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    def db():
        with factory() as session:yield session
    main.app.dependency_overrides[main.db]=db
    try:
        a,b=TestClient(main.app),TestClient(main.app)
        def post(client,path,body):
            return client.post(path,json=body,
                headers={"X-CSRF-Token":client.cookies.get("csrf_token","")})
        for client,slug in ((a,"remind-a"),(b,"remind-b")):
            assert post(client,"/api/register",{"school_name":slug,"slug":slug,
                "email":slug+"@example.test","password":"demonstration-password-123"}).status_code==201
        sid=a.get("/api/me").json()["sid"]
        uid=a.get("/api/me").json()["uid"]
        learner=post(a,"/api/learners",{"admission_no":"Q01","first_name":"Sensitive",
            "surname":"Example","grade":"5","class_name":"5A"}).json()["id"]
        with factory() as s:
            case=main.Case(school_id=sid,learner_id=learner,title="Fictional case")
            s.add(case);s.flush()
            item=operations.FollowUp(school_id=sid,case_id=case.id,
                owner_user_id=uid,summary="Review records",
                due_at=datetime.now(timezone.utc)+timedelta(hours=2))
            s.add(item);s.commit()
        first=post(a,"/api/automation/followups/queue-reminders",{})
        assert first.status_code==200,first.text
        assert first.json()["queued"]==1
        second=post(a,"/api/automation/followups/queue-reminders",{})
        assert second.status_code==200 and second.json()["queued"]==0
        assert b.get("/api/automation/followups/due").json()["items"]==[]
        assert len(a.get("/api/automation/followups/due").json()["items"])==1
        with factory() as s:
            rows=s.scalars(select(EmailOutbox).where(EmailOutbox.school_id==sid)).all()
            assert len(rows)==1
            assert rows[0].status=="pending"
            assert "Sensitive" not in rows[0].body
            assert "Fictional case" not in rows[0].body
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
