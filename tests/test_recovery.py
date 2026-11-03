"""Tests for SMTP-configured one-use password recovery and session invalidation."""
import os
os.environ.setdefault("JWT_SECRET","unit-test-only-key")
os.environ["DATABASE_URL"]="sqlite://"
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app import main, account_recovery

def test_password_recovery(monkeypatch):
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    Session=sessionmaker(engine,expire_on_commit=False)
    def db():
        with Session() as s:yield s
    main.app.dependency_overrides[main.db]=db
    delivered={}
    monkeypatch.setattr(account_recovery,"send_email",lambda destination,token:delivered.update(email=destination,token=token))
    for key in ("SMTP_HOST","SMTP_USERNAME","SMTP_PASSWORD","SMTP_FROM","APP_PUBLIC_URL"):
        monkeypatch.setenv(key,"test-value")
    try:
        client=TestClient(main.app)
        def post(path,data):
            return client.post(path,json=data,headers={"X-CSRF-Token":client.cookies.get("csrf_token","")})
        assert post("/api/register",{"school_name":"Recovery Demo School","slug":"recover-demo",
            "email":"owner@example.test","password":"old-test-password-12"}).status_code==201
        old_cookie=client.cookies.get("session")
        response=post("/api/account-recovery/request",{"email":"owner@example.test"})
        assert response.status_code==200
        assert delivered["email"]=="owner@example.test"
        token=delivered["token"]
        assert post("/api/account-recovery/complete",{"token":token,"password":"new-test-password-34"}).status_code==200
        assert post("/api/account-recovery/complete",{"token":token,"password":"another-password"}).status_code==400
        old=TestClient(main.app)
        old.cookies.set("session",old_cookie)
        assert old.get("/api/me").json()["authenticated"] is False
        assert post("/api/login",{"school_slug":"recover-demo","email":"owner@example.test","password":"new-test-password-34"}).status_code==200
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
