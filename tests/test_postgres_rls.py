"""PostgreSQL RLS integration test. Run in isolated CI with an empty database."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from fastapi.testclient import TestClient
from app import main

def test_postgres_school_isolation_and_rls():
    if main.engine.dialect.name!="postgresql":
        pytest.skip("PostgreSQL RLS runs in its dedicated CI job")
    a,b=TestClient(main.app),TestClient(main.app)
    def send(c,path,payload):
        return c.post(path,json=payload,headers={"X-CSRF-Token":c.cookies.get("csrf_token","")})
    for c,slug in ((a,"rls-demo-one"),(b,"rls-demo-two")):
        response=send(c,"/api/register",{"school_name":slug,"slug":slug,
            "email":slug+"@example.invalid","password":"safe-example-password-1234"})
        assert response.status_code==201,response.text
    response=send(a,"/api/learners",{"admission_no":"RLS-01","first_name":"Fictional",
        "surname":"Student","grade":"5","class_name":"5A"})
    assert response.status_code==201,response.text
    assert len(a.get("/api/learners").json())==1
    assert b.get("/api/learners").json()==[]
    with main.engine.connect() as conn:
        # FORCE RLS applies even to the test database owner. No request tenant
        # identity means school-owned tables have no visible rows.
        assert conn.execute(text("select count(*) from learners")).scalar_one()==0
        for table in ("case_events","follow_ups","guardians","class_assignments",
                      "learner_placements","learner_observations","review_tasks",
                      "school_settings","letter_documents","school_documents",
                      "appointments","parent_contacts"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()==0
    with pytest.raises(DBAPIError):
        with main.engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.school_id', :sid, true)"),
                {"sid":str(a.get("/api/me").json()["sid"])})
            conn.execute(text(
                "INSERT INTO school_settings(school_id,key,value) "
                "VALUES (:other,'forbidden_rls_change','bad')"),
                {"other":b.get("/api/me").json()["sid"]})

    cross=send(b,"/api/incidents",{"learner_id":response.json()["id"],
        "offence_id":1,"location":"No access","description":"Invalid cross-school",
        "immediate_action":"Reject"})
    assert cross.status_code in (403,404)
