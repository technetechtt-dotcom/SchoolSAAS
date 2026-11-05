"""Optional Paystack provider integration with verified, idempotent settlements.

Requires merchant-managed PAYSTACK_SECRET_KEY and PAYSTACK_WEBHOOK_SECRET.
No direct charges or recurring mandates are initiated by this module.
"""
import hashlib,hmac,json,os,re,secrets,time
from datetime import datetime,timezone
from urllib.parse import urlparse
import httpx
from fastapi import APIRouter,Depends,HTTPException,Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import main as m
from app.pilot_pack import Invoice,PaymentEvent

router=APIRouter(prefix="/api",tags=["payments"])
API_BASE="https://api.paystack.co"

def configured():
    return (os.getenv("BILLING_GATEWAY","").lower()=="paystack"
        and os.getenv("PAYSTACK_SECRET_KEY","").startswith(("sk_test_","sk_live_"))
        and os.getenv("PAYSTACK_WEBHOOK_SECRET","").startswith("whsec_"))

def require_config():
    if not configured():raise HTTPException(503,"Paystack merchant credentials and signing secret are not configured")
    if os.getenv("PAYSTACK_SECRET_KEY","").startswith("sk_live_"):
        public=os.getenv("APP_PUBLIC_URL","")
        if not public.startswith("https://"):
            raise HTTPException(503,"Production checkout requires an HTTPS public application URL")
    return os.environ["PAYSTACK_SECRET_KEY"]

def provider_request(method,path,payload=None):
    secret=require_config()
    try:
        with httpx.Client(timeout=12,follow_redirects=False) as client:
            result=client.request(method,API_BASE+path,
                headers={"Authorization":"Bearer "+secret,"Content-Type":"application/json"},
                json=payload)
            result.raise_for_status()
            data=result.json()
    except (httpx.HTTPError,ValueError) as exc:
        raise HTTPException(502,"Payment provider unavailable or returned an invalid response") from exc
    if data.get("status") is not True or not isinstance(data.get("data"),dict):
        raise HTTPException(502,"Payment provider rejected the request")
    return data["data"]

def checkout(invoice_id:int,s:Session,ctx:dict):
    require_config()
    row=s.scalar(select(Invoice).where(Invoice.id==invoice_id,
        Invoice.school_id==ctx["sid"]).with_for_update())
    if not row:raise HTTPException(404,"Invoice not found")
    if row.status!="issued" or row.payment_ref:
        raise HTTPException(409,"Invoice has already entered payment processing")
    if row.currency.upper()!="ZAR" or row.amount_cents<=0:
        raise HTTPException(400,"Only positive ZAR invoices are supported")
    payer=s.get(m.User,ctx["uid"])
    if not payer or not payer.active:
        raise HTTPException(403,"Valid school payer account required")
    reference=f"sc{row.school_id}-{row.id}-{secrets.token_hex(10)}"
    data=provider_request("POST","/transaction/initialize",{
        "email":payer.email,"amount":row.amount_cents,"currency":"ZAR","reference":reference,
        "callback_url":os.environ.get("APP_PUBLIC_URL","").rstrip("/")+"/#/billing",
    })
    auth_url=data.get("authorization_url","")
    parsed=urlparse(auth_url)
    if data.get("reference")!=reference or parsed.scheme!="https" or parsed.hostname!="checkout.paystack.com":
        raise HTTPException(502,"Provider supplied an unexpected payment destination")
    row.payment_ref=reference
    row.gateway="paystack"
    row.status="awaiting_payment"
    m.log(s,ctx,"checkout","invoice",row.id)
    s.commit()
    return {"id":row.id,"provider":"paystack","status":row.status,
            "authorization_url":auth_url,"payment_ref":reference,
            "message":"Payment checkout ready; invoice remains unpaid until verified settlement"}

def signed_event(header:str,body:bytes):
    secret=os.getenv("PAYSTACK_WEBHOOK_SECRET","")
    if not secret.startswith("whsec_"):raise HTTPException(503,"Paystack webhook signing secret missing")
    fields=header.split(",")
    timestamps=[v[2:] for v in fields if v.startswith("t=")]
    signatures=[v.split(":",1)[1] for v in fields
                if v.startswith("v1=") and ":" in v]
    if len(timestamps)!=1 or not timestamps[0].isdigit() or not signatures:
        raise HTTPException(401,"Missing signed event timestamp or signature")
    if abs(int(time.time())-int(timestamps[0]))>300:
        raise HTTPException(401,"Webhook signature expired")
    expected=hmac.new(secret.encode(),timestamps[0].encode()+b"."+body,hashlib.sha512).hexdigest()
    if not any(hmac.compare_digest(expected,signature) for signature in signatures):
        raise HTTPException(401,"Invalid webhook signature")
    try:
        return json.loads(body)
    except (ValueError,UnicodeError):
        raise HTTPException(400,"Invalid payment event body")

@router.post("/billing/webhooks/paystack")
async def paystack_webhook(request:Request,s:Session=Depends(m.db)):
    require_config()
    raw=await request.body()
    if len(raw)>262144:raise HTTPException(413,"Payment event too large")
    event=signed_event(request.headers.get("paystack-signature",""),raw)
    if event.get("event")!="charge.success":return {"ok":True,"ignored":True}
    event_data=event.get("data") or {}
    reference=event_data.get("reference","")
    if not isinstance(reference,str) or not re.fullmatch(r"[A-Za-z0-9.=-]{1,80}",reference):
        raise HTTPException(400,"Invalid payment reference")
    row=s.scalar(select(Invoice).where(Invoice.payment_ref==reference,
        Invoice.gateway=="paystack").with_for_update())
    if not row:raise HTTPException(404,"Unknown transaction reference")
    if row.status=="paid_gateway":
        return {"ok":True,"already_processed":True}
    if row.status!="awaiting_payment":
        raise HTTPException(409,"Invoice is not awaiting a verified payment")
    verified=provider_request("GET","/transaction/verify/"+reference)
    if (verified.get("reference")!=reference or verified.get("status")!="success"
        or verified.get("currency","").upper()!=row.currency.upper()
        or type(verified.get("amount")) is not int or verified["amount"]!=row.amount_cents):
        raise HTTPException(409,"Provider settlement does not match the invoice")
    transaction_id=str(verified.get("id",""))
    if not transaction_id.isdigit():
        raise HTTPException(409,"Missing verified provider transaction identifier")
    duplicate=s.scalar(select(PaymentEvent).where(
        PaymentEvent.provider=="paystack",PaymentEvent.external_ref==transaction_id))
    if duplicate:raise HTTPException(409,"Verified payment already assigned to an invoice")
    row.status="paid_gateway"
    row.paid_at=datetime.now(timezone.utc)
    s.add(PaymentEvent(school_id=row.school_id,invoice_id=row.id,
        provider="paystack",event_type="charge.success",external_ref=transaction_id,
        payload="verified-invoice:"+str(row.id)))
    s.commit()
    # Subscription entitlements are not granted until a verified plan is linked to the invoice.
    return {"ok":True,"status":row.status,"subscription_activated":False}
