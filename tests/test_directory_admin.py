"""Regression tests for large-school directory, import and academic settings."""
import os
os.environ.setdefault("JWT_SECRET","unit-test-only-secret-not-for-deployment")
os.environ["DATABASE_URL"]="sqlite://"
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app import main

def test_bulk_import_directory_academic_and_switching():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    Session=sessionmaker(engine,expire_on_commit=False)
    def db():
        with Session() as s:
            yield s
    main.app.dependency_overrides[main.db]=db
    try:
        a,b=TestClient(main.app),TestClient(main.app)
        def send(c,path,payload,method="post"):
            return getattr(c,method)(path,json=payload,headers={"X-CSRF-Token":c.cookies.get("csrf_token","")})
        for c,slug in ((a,"alpha-school"),(b,"beta-school")):
            assert send(c,"/api/register",{"school_name":slug,"slug":slug,"email":slug+"@example.test","password":"long-test-password-999"}).status_code==201
        rows=[{"admission_no":str(i).zfill(4),"first_name":"Learner","surname":"Sample"+str(i),
               "grade":"5","class_name":"5A"} for i in range(125)]
        response=send(a,"/api/learners/import",{"rows":rows})
        assert response.status_code==201,response.text
        assert response.json()["created"]==125
        response=send(a,"/api/learners/import",{"rows":rows[:1]})
        assert response.status_code==201 and response.json()["created"]==0 and len(response.json()["skipped"])==1
        page=a.get("/api/directory/learners?limit=50&offset=100").json()
        assert page["total"]==125 and len(page["items"])==25
        found=a.get("/api/directory/learners?q=Sample104").json()
        assert found["total"]==1
        assert b.get("/api/directory/learners").json()["total"]==0
        assert send(a,"/api/settings/academic",{"academic_year":2027,"term":2,"school_contact_email":"school@example.test"},method="put").status_code==200
        assert a.get("/api/settings/academic").json()["term"]==2
        assert b.get("/api/settings/academic").json()["term"]==1
        assert len(a.get("/api/mine/schools").json())==1
        assert send(a,"/api/mine/schools/switch",{"school_id":2}).status_code==403
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
