"""Regression tests for educator evidence scope and sensitive learner profiles."""
import os
os.environ.setdefault("JWT_SECRET","security-test-secret-32-characters")
os.environ["DATABASE_URL"]="sqlite://"
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from app import main

def test_evidence_access_and_sensitive_journey():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    Session=sessionmaker(engine,expire_on_commit=False)
    def db():
        with Session() as s: yield s
    main.app.dependency_overrides[main.db]=db
    try:
        admin,teacher=TestClient(main.app),TestClient(main.app)
        def write(client,url,payload):
            return client.post(url,json=payload,headers={"X-CSRF-Token":client.cookies.get("csrf_token","")})
        assert write(admin,"/api/register",{"school_name":"Scoped Demo","slug":"scoped-demo",
            "email":"admin@scope.test","password":"example-password-123456"}).status_code==201
        for idx,clazz in enumerate(("6A","7B"),1):
            assert write(admin,"/api/learners",{"admission_no":str(idx),"first_name":"Test",
                "surname":clazz,"grade":clazz[0],"class_name":clazz}).status_code==201
        offense=write(admin,"/api/offences",{"code":"T01","name":"Practice",
            "category":"test","severity":1}).json()["id"]
        i=write(admin,"/api/incidents",{"learner_id":1,"offence_id":offense,
            "location":"Demo","description":"Example incident","immediate_action":"Support"}).json()["id"]
        token=write(admin,"/api/invitations",{"email":"teacher@scope.test","role":"educator","assigned_class":"6A"}).json()["token"]
        assert write(teacher,"/api/invitations/accept",{"token":token,
            "password":"example-teacher-password"}).status_code==201
        assert write(teacher,"/api/login",{"school_slug":"scoped-demo","email":"teacher@scope.test",
            "password":"example-teacher-password"}).status_code==200
        def upload(incident_id=None,case_id=None):
            fields={}
            if incident_id:fields["incident_id"]=str(incident_id)
            if case_id:fields["case_id"]=str(case_id)
            return teacher.post("/api/evidence",data=fields,
                files={"file":("note.txt",b"demo","text/plain")},
                headers={"X-CSRF-Token":teacher.cookies.get("csrf_token","")})
        assert upload(incident_id=i).status_code==403
        assert upload(case_id=100).status_code==403
        own=write(teacher,"/api/incidents",{"learner_id":1,"offence_id":offense,
            "location":"Classroom","description":"Educator example","immediate_action":"Review"}).json()["id"]
        assert upload(incident_id=own).status_code==201
        assert teacher.get("/api/learners/1/journey").status_code==403
        assert teacher.get("/api/learners/1/intervention-recommendations").status_code==403
        assert admin.get("/api/learners/1/journey").status_code==200
        assert write(admin,"/api/learners/1/observations",{"learner_id":1,"grade_at_time":"6",
            "domain":"cognitive_assessment","title":"Example",
            "summary":"Not verified","source":"classroom_observation"}).status_code==422
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
