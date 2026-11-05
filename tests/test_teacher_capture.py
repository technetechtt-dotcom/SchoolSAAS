"""Teacher shortcuts do not leak activity across reporters or schools."""
import os
os.environ.setdefault("JWT_SECRET","test-only-teacher-shortcuts-key")
os.environ["DATABASE_URL"]="sqlite://"
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app import main

def test_teacher_shortcuts_are_school_and_reporter_scoped():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    def db():
        with factory() as session:yield session
    main.app.dependency_overrides[main.db]=db
    try:
        admin,other=TestClient(main.app),TestClient(main.app)
        def post(client,path,body):
            return client.post(path,json=body,
                headers={"X-CSRF-Token":client.cookies.get("csrf_token","")})
        for client,slug in ((admin,"shortcuts-a"),(other,"shortcuts-b")):
            assert post(client,"/api/register",{"school_name":slug,
                "slug":slug,"email":slug+"@example.test",
                "password":"test-password-12345678"}).status_code==201
        learner=post(admin,"/api/learners",{"admission_no":"A01","first_name":"Example",
            "surname":"Learner","grade":"6","class_name":"6A"}).json()["id"]
        offence=post(admin,"/api/offences",{"code":"C1","name":"Classroom conduct",
            "category":"Behaviour","severity":1}).json()["id"]
        assert post(admin,"/api/incidents",{"learner_id":learner,"offence_id":offence,
            "location":"Playground","description":"Fictional event",
            "immediate_action":"No immediate action"}).status_code==201
        mine=admin.get("/api/teacher/incident-shortcuts")
        assert mine.status_code==200
        assert mine.json()["last_location"]=="Playground"
        assert mine.json()["favourite_offence_ids"]==[offence]
        empty=other.get("/api/teacher/incident-shortcuts")
        assert empty.status_code==200
        assert empty.json()["favourite_offence_ids"]==[]
        assert empty.json()["recent_learner_ids"]==[]
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
