"""Optional Paystack integration only settles after signed webhook and verified amount."""
import os,hmac,hashlib,json,time
os.environ.setdefault("JWT_SECRET","payment-integration-test-key")
os.environ["DATABASE_URL"]="sqlite://"
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app import main,paystack_integration

def test_paystack_checkout_and_verified_webhook(monkeypatch):
    monkeypatch.setenv("BILLING_GATEWAY","paystack")
    monkeypatch.setenv("PAYSTACK_SECRET_KEY","sk_test_fictional-key")
    monkeypatch.setenv("PAYSTACK_WEBHOOK_SECRET","whsec_fictional-signing-key")
    monkeypatch.setenv("APP_PUBLIC_URL","https://school.example.test")
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    def db():
        with factory() as s:yield s
    main.app.dependency_overrides[main.db]=db
    verified_amount={"value":15000}
    def fake_provider(method,path,payload=None):
        if method=="POST":
            assert payload["amount"]==15000
            assert payload["currency"]=="ZAR"
            return {"reference":payload["reference"],
                    "authorization_url":"https://checkout.paystack.com/exampletest"}
        assert method=="GET" and path.startswith("/transaction/verify/")
        return {"reference":path.rsplit("/",1)[-1],
                "status":"success","currency":"ZAR","amount":verified_amount["value"],"id":3456781}
    monkeypatch.setattr(paystack_integration,"provider_request",fake_provider)
    try:
        admin,other=TestClient(main.app),TestClient(main.app)
        def post(c,path,data=None):
            return c.post(path,json=data or {},headers={"X-CSRF-Token":c.cookies.get("csrf_token","")})
        for client,slug in ((admin,"paystack-a"),(other,"paystack-b")):
            assert post(client,"/api/register",{"school_name":slug,
                "slug":slug,"email":slug+"@example.test",
                "password":"example-password-for-testing"}).status_code==201
        invoice=post(admin,"/api/billing/invoices",{"amount_cents":15000,"description":"School plan"})
        assert invoice.status_code==201,invoice.text
        iid=invoice.json()["id"]
        assert post(other,f"/api/billing/invoices/{iid}/checkout").status_code==404
        checkout=post(admin,f"/api/billing/invoices/{iid}/checkout")
        assert checkout.status_code==200,checkout.text
        assert checkout.json()["authorization_url"].startswith("https://checkout.paystack.com/")
        assert post(admin,f"/api/billing/invoices/{iid}/checkout").status_code==409
        reference=checkout.json()["payment_ref"]
        body=json.dumps({"event":"charge.success","data":{"reference":reference}},
                         separators=(",",":")).encode()
        when=str(int(time.time()))
        signature=hmac.new(b"whsec_fictional-signing-key",when.encode()+b"."+body,hashlib.sha512).hexdigest()
        headers={"Content-Type":"application/json","Paystack-Signature":f"t={when},v1=whk_test:{signature}",
            "X-CSRF-Token":admin.cookies.get("csrf_token","")}
        assert admin.post("/api/billing/webhooks/paystack",content=body,
            headers={**headers,"Paystack-Signature":"t=1,v1=whk_bad:0"}).status_code==401
        verified_amount["value"]=14900
        assert admin.post("/api/billing/webhooks/paystack",content=body,headers=headers).status_code==409
        verified_amount["value"]=15000
        confirmed=admin.post("/api/billing/webhooks/paystack",content=body,headers=headers)
        assert confirmed.status_code==200,confirmed.text
        assert confirmed.json()["subscription_activated"] is False
        again=admin.post("/api/billing/webhooks/paystack",content=body,headers=headers)
        assert again.status_code==200 and again.json()["already_processed"] is True
        assert admin.get("/api/subscription").json()["plan"]!="standard"
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
