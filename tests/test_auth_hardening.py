"""Security regression for revocable sessions, login limits, manager case lookup and CSV safety."""
import os
os.environ.setdefault("JWT_SECRET","test-secret-only-not-for-deployment")
os.environ["DATABASE_URL"]="sqlite://"
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app import main

def test_sessions_case_assignees_and_csv_formula_safety():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    Session=sessionmaker(engine,expire_on_commit=False)
    def db():
        with Session() as s:yield s
    main.app.dependency_overrides[main.db]=db
    try:
        admin=TestClient(main.app)
        def send(client,route,data,method="post"):
            return getattr(client,method)(route,json=data,headers={"X-CSRF-Token":client.cookies.get("csrf_token","")})
        assert send(admin,"/api/register",{"school_name":"Safety Test School","slug":"security-school",
            "email":"admin@school.test","password":"demo-password-123456"}).status_code==201
        token=admin.cookies.get("session")
        learner=send(admin,"/api/learners",{"admission_no":"A001","first_name":"Test",
            "surname":"Learner","grade":"6","class_name":"6A"}).json()["id"]
        assert send(admin,"/api/offences",{"code":"S1","name":"Other","category":"Testing","severity":1}).status_code==201
        assert send(admin,"/api/incidents",{"learner_id":learner,"offence_id":1,
            "location":"=1+1","description":"Fictitious","immediate_action":"Review"}).status_code==201
        export=admin.get("/api/reports/incidents.csv")
        assert export.status_code==200 and "'=1+1" in export.text
        invite=send(admin,"/api/invitations",{"email":"hod@school.test","role":"hod"}).json()["token"]
        hod=TestClient(main.app)
        assert send(hod,"/api/invitations/accept",{"token":invite,"password":"demo-password-987654"}).status_code==201
        assert send(hod,"/api/login",{"school_slug":"security-school","email":"hod@school.test","password":"demo-password-987654"}).status_code==200
        assert hod.get("/api/members").status_code==403
        assignees=hod.get("/api/case-assignees")
        assert assignees.status_code==200
        assert any(item["label"]=="hod@school.test" for item in assignees.json())
        assert admin.get("/api/me").status_code==200
        assert send(admin,"/api/logout",{}).status_code==200
        old=TestClient(main.app)
        old.cookies.set("session",token)
        assert old.get("/api/me").status_code==401
        for _ in range(5):
            assert send(admin,"/api/login",{"school_slug":"security-school","email":"admin@school.test","password":"wrong"}).status_code==401
        locked=send(admin,"/api/login",{"school_slug":"security-school","email":"admin@school.test","password":"demo-password-123456"})
        assert locked.status_code==429
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
