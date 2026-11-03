"""Run with JWT_SECRET=test-secret-for-local-tests-only pytest -q"""
import os
os.environ.setdefault("JWT_SECRET","test-secret-for-local-tests-only")
os.environ["DATABASE_URL"]="sqlite://"
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app import main

def test_school_boundaries():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    Session=sessionmaker(engine,expire_on_commit=False)
    def override_db():
        with Session() as s:
            yield s
    main.app.dependency_overrides[main.db]=override_db
    try:
        a=TestClient(main.app)
        b=TestClient(main.app)
        def write(client,path,data):
            return client.post(path,headers={"X-CSRF-Token":client.cookies.get("csrf_token","")},json=data)
        assert write(a,"/api/register",{"school_name":"School One","slug":"school-one","email":"a@example.test","password":"this-is-a-demo-pass-123"}).status_code==201
        assert write(b,"/api/register",{"school_name":"School Two","slug":"school-two","email":"b@example.test","password":"this-is-a-demo-pass-123"}).status_code==201
        ra=write(a,"/api/learners",{"admission_no":"001","first_name":"Private","surname":"Learner","grade":"4","class_name":"4A"})
        assert ra.status_code==201
        assert b.get("/api/learners").json()==[]
        assert write(b,"/api/offences",{"code":"B001","name":"Disruption","category":"Conduct","severity":1}).status_code==201
        assert write(b,"/api/incidents",{"learner_id":ra.json()["id"],"offence_id":1,"location":"Classroom","description":"Test","immediate_action":"Monitor"}).status_code==404
        assert a.get("/api/dashboard").json()["learners"]==1
        assert b.get("/api/dashboard").json()["learners"]==0
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
