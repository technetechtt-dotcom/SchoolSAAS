"""Management referral drafts must be tenant-scoped and avoid re-entry."""
import os
os.environ.setdefault("JWT_SECRET","test-referral-secret-only")
os.environ["DATABASE_URL"]="sqlite://"
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app import main

def test_prepare_referral_reuses_incident_and_keeps_draft_status():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    def db():
        with factory() as s:yield s
    main.app.dependency_overrides[main.db]=db
    try:
        a,b=TestClient(main.app),TestClient(main.app)
        def send(client,path,body):
            return client.post(path,json=body,
                headers={"X-CSRF-Token":client.cookies.get("csrf_token","")})
        for client,slug in ((a,"referral-school-one"),(b,"referral-school-two")):
            assert send(client,"/api/register",{"school_name":slug,"slug":slug,
                "email":slug+"@example.test","password":"test-password-12345678"}).status_code==201
        learner=send(a,"/api/learners",{"admission_no":"TEST01","first_name":"Fictional",
            "surname":"Learner","grade":"7","class_name":"7C"}).json()["id"]
        offence=send(a,"/api/offences",{"code":"R1","name":"Support review",
            "category":"Conduct","severity":1}).json()["id"]
        incident=send(a,"/api/incidents",{"learner_id":learner,"offence_id":offence,
            "location":"Hall","description":"A test-only description",
            "immediate_action":"Restorative conversation"}).json()["id"]
        path=f"/api/automation/incidents/{incident}/referral-draft"
        assert send(b,path,{}).status_code==404
        first=send(a,path,{})
        assert first.status_code==201,first.text
        again=send(a,path,{})
        assert again.status_code==201 and again.json()["id"]==first.json()["id"]
        doc=a.get("/api/documents/"+str(first.json()["id"]))
        assert doc.status_code==200
        payload=doc.json()
        assert payload["status"]=="draft"
        assert "Fictional Learner" in payload["body"]
        assert "A test-only description" in payload["body"]
        assert "not a finding of misconduct" in payload["body"]
        assert b.get("/api/documents/"+str(first.json()["id"])).status_code==404
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
