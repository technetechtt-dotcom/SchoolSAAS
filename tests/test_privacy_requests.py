"""Privacy request workflow must remain school scoped and identity-gated."""
import os
os.environ.setdefault("JWT_SECRET","privacy-test-only-key")
os.environ["DATABASE_URL"]="sqlite://"
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app import main

def test_privacy_requests_are_scoped_and_require_identity():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    Session=sessionmaker(engine,expire_on_commit=False)
    def db():
        with Session() as s: yield s
    main.app.dependency_overrides[main.db]=db
    try:
        a,b=TestClient(main.app),TestClient(main.app)
        def send(c,path,payload,method="post"):
            return getattr(c,method)(path,json=payload,
                headers={"X-CSRF-Token":c.cookies.get("csrf_token","")})
        for c,slug in ((a,"data-a"),(b,"data-b")):
            assert send(c,"/api/register",{"school_name":slug,"slug":slug,
                "email":slug+"@example.test","password":"demonstration-password-123"}).status_code==201
        req=send(a,"/api/privacy/requests",{"request_type":"access",
            "requester_name":"Example Guardian","requester_contact":"guardian@example.test"})
        assert req.status_code==201
        identifier=req.json()["id"]
        assert len(a.get("/api/privacy/requests").json())==1
        assert b.get("/api/privacy/requests").json()==[]
        incomplete=send(a,f"/api/privacy/requests/{identifier}",{
            "verification_status":"unverified","status":"fulfilled","notes":"Not yet verified"},"patch")
        assert incomplete.status_code==409
        verified=send(a,f"/api/privacy/requests/{identifier}",{
            "verification_status":"verified","status":"fulfilled","notes":"Identity and legal review documented"},"patch")
        assert verified.status_code==200
        assert send(b,f"/api/privacy/requests/{identifier}",{
            "verification_status":"verified","status":"fulfilled"},"patch").status_code==404
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
