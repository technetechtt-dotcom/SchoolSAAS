"""v0.3 regression coverage for school-scoped detail and workflow endpoints."""
import os
os.environ.setdefault("JWT_SECRET","unit-test-only-secret-not-for-deployment")
os.environ["DATABASE_URL"]="sqlite://"
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app import main
from app import pilot_pack, operations, extended  # noqa: F401
from tests.conftest import finish_required_onboarding

def test_extended_workflows_and_tenant_boundaries():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    Session=sessionmaker(engine,expire_on_commit=False)
    def db():
        with Session() as session:
            yield session
    main.app.dependency_overrides[main.db]=db
    try:
        a,b=TestClient(main.app),TestClient(main.app)
        def write(c,path,payload,method="post"):
            return getattr(c,method)(path,json=payload,headers={"X-CSRF-Token":c.cookies.get("csrf_token","")})
        for c,slug in [(a,"example-one"),(b,"example-two")]:
            assert write(c,"/api/register",{"school_name":"School "+slug,"slug":slug,"email":slug+"@example.test","password":"strong-demonstration-password"}).status_code==201
        l=write(a,"/api/learners",{"admission_no":"111","first_name":"Example","surname":"Student","grade":"5","class_name":"5A"}).json()["id"]
        assert b.get("/api/learners/"+str(l)).status_code==404
        assert a.get("/api/learners/"+str(l)).json()["first_name"]=="Example"
        assert write(a,"/api/offences",{"code":"B01","name":"Disruption","category":"Conduct","severity":3}).status_code==201
        i=write(a,"/api/incidents",{"learner_id":l,"offence_id":1,"location":"Classroom","description":"Fictional sample","immediate_action":"Referral"}).json()["id"]
        assert a.get("/api/incidents/"+str(i)).status_code==200
        assert b.get("/api/incidents/"+str(i)).status_code==404
        finish_required_onboarding(a, lambda path,payload=None,method="post": write(a,path,payload or {},method))
        case=write(a,"/api/cases",{"learner_id":l,"title":"Example case","incident_ids":[i]}).json()["id"]
        assert a.get("/api/cases/"+str(case)).json()["incident_ids"]==[i]
        assert b.get("/api/cases/"+str(case)).status_code==404
        assert write(a,"/api/appointments",{"learner_id":l,"title":"Parent meeting","scheduled_at":"2026-12-03T10:00:00+02:00"}).status_code==201
        assert len(a.get("/api/appointments").json())==1
        assert b.get("/api/appointments").json()==[]
        assert write(a,"/api/appeals",{"case_id":case,"reason":"Request a formal review"}).status_code==201
        assert len(a.get("/api/appeals").json())==1
        assert b.get("/api/appeals").json()==[]
        assert write(a,"/api/documents",{"learner_id":l,"title":"Meeting letter","body":"Draft notice for staff review","document_type":"letter"}).status_code==201
        assert "Draft notice" in a.get("/api/documents/1").json()["body"]
        assert b.get("/api/documents/1").status_code==404
        assert a.get("/api/classes").json()[0]["class_name"]=="5A"
        assert len(a.get("/api/notifications").json())==1
        export=a.get("/api/reports/incidents.csv")
        assert export.status_code==200 and "Incident ID" in export.text
        assert a.get("/api/subscription").json()["billing_enabled"] is False
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
