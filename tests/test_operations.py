"""Tenant-scope and workflow tests for v0.5 school operations."""
import os
os.environ.setdefault("JWT_SECRET","testing-only-not-deployment")
os.environ["DATABASE_URL"]="sqlite://"
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app import main

def test_guardians_case_timeline_followups_and_classes():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    def db():
        with factory() as s:yield s
    main.app.dependency_overrides[main.db]=db
    try:
        clients=[TestClient(main.app),TestClient(main.app)]
        def submit(c,url,payload,method="post"):
            return getattr(c,method)(url,json=payload,headers={"X-CSRF-Token":c.cookies.get("csrf_token","")})
        for idx,c in enumerate(clients):
            assert submit(c,"/api/register",{"school_name":f"Demo {idx} school","slug":f"demo-ops-{idx}",
                "email":f"admin{idx}@invalid.test","password":"testing-only-password-123"}).status_code==201
        a,b=clients
        student=submit(a,"/api/learners",{"admission_no":"001","first_name":"Demo","surname":"Student","grade":"6","class_name":"6A"}).json()["id"]
        assert submit(a,"/api/guardians",{"learner_id":student,"name":"Example Guardian","relationship":"Parent",
            "email":"guardian@invalid.test","phone":"000"}).status_code==201
        assert len(a.get("/api/guardians",params={"learner_id":student}).json())==1
        assert b.get("/api/guardians",params={"learner_id":student}).status_code==404
        submit(a,"/api/offences",{"code":"B1","name":"Example","category":"Behaviour","severity":1})
        incident=submit(a,"/api/incidents",{"learner_id":student,"offence_id":1,"location":"Classroom",
            "description":"Imaginary event","immediate_action":"Discuss"}).json()["id"]
        case=submit(a,"/api/cases",{"learner_id":student,"title":"Test case","incident_ids":[incident]}).json()["id"]
        assert submit(a,f"/api/cases/{case}/timeline",{"kind":"meeting","note":"Meeting planned"}).status_code==201
        assert len(a.get(f"/api/cases/{case}/timeline").json())==1
        assert b.get(f"/api/cases/{case}/timeline").status_code==404
        assert submit(a,f"/api/cases/{case}/follow-ups",{"owner_user_id":1,
            "summary":"Check progress","due_at":"2027-01-10T10:00:00+02:00"}).status_code==201
        assert a.get(f"/api/cases/{case}/follow-ups").json()[0]["status"]=="open"
        assert submit(a,"/api/class-assignments",{"user_id":1,"class_name":"6A"}).status_code==201
        assert len(a.get("/api/class-assignments").json())==1
        assert submit(b,"/api/class-assignments",{"user_id":1,"class_name":"6A"}).status_code==400
        assert a.get("/api/directory/incidents?limit=2").json()["total"]==1
        assert a.get("/api/directory/cases?limit=2").json()["total"]==1
        assert b.get("/api/directory/cases").json()["total"]==0
        assert a.get("/api/dashboard/aggregates").json()["incidents"]==1
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
