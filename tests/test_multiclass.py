"""Verify educator has access to multiple assigned classes, not the rest of a school."""
import os
os.environ.setdefault("JWT_SECRET","local-security-test-secret")
os.environ["DATABASE_URL"]="sqlite://"
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app import main

def test_multi_class_scope():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    Session=sessionmaker(engine,expire_on_commit=False)
    def db():
        with Session() as s:yield s
    main.app.dependency_overrides[main.db]=db
    try:
        admin,teacher=TestClient(main.app),TestClient(main.app)
        def write(c,url,value):
            return c.post(url,json=value,headers={"X-CSRF-Token":c.cookies.get("csrf_token","")})
        assert write(admin,"/api/register",{"school_name":"Multi Class Demo","slug":"multiclass","email":"admin@test.invalid","password":"a-safe-fake-password"}).status_code==201
        for idx,clazz in enumerate(("5A","6B","7C")):
            assert write(admin,"/api/learners",{"admission_no":f"{idx}","first_name":"Demo","surname":clazz,"grade":clazz[0],"class_name":clazz}).status_code==201
        invite=write(admin,"/api/invitations",{"email":"teacher@test.invalid","role":"educator","assigned_class":"5A"}).json()["token"]
        assert write(teacher,"/api/invitations/accept",{"token":invite,"password":"another-fake-password"}).status_code==201
        assert write(teacher,"/api/login",{"school_slug":"multiclass","email":"teacher@test.invalid","password":"another-fake-password"}).status_code==200
        assert len(teacher.get("/api/directory/learners").json()["items"])==1
        user_id=admin.get("/api/members").json()[1]["user_id"]
        assert write(admin,"/api/class-assignments",{"user_id":user_id,"class_name":"6B"}).status_code==201
        assert {x["class_name"] for x in teacher.get("/api/directory/learners").json()["items"]}=={"5A","6B"}
        assert teacher.get("/api/learners/3").status_code==403
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
