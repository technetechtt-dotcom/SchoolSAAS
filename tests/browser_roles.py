"""Real-browser role navigation checks using isolated fictional school records.

Run against a running test server. Requires SCHOOLCARE_URL and local DATABASE_URL.
"""
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from uuid import uuid4
from playwright.sync_api import sync_playwright
from fastapi.testclient import TestClient
from app import main

BASE=os.environ.get("SCHOOLCARE_URL","http://127.0.0.1:8000")
slug="roles-"+uuid4().hex[:10]
password="fictional-testing-password-1234"
admin=TestClient(main.app)

def post(client,path,data):
    return client.post(path,json=data,
        headers={"X-CSRF-Token":client.cookies.get("csrf_token","")})

def seed():
    response=post(admin,"/api/register",{"school_name":"Role Browser Example",
        "slug":slug,"email":slug+"@example.test","password":password})
    assert response.status_code==201,response.text
    for role in ("educator","hod","smt","principal"):
        email=f"{role}-{slug}@example.test"
        invite=post(admin,"/api/invitations",{
            "email":email,"role":role,"assigned_class":"5A" if role=="educator" else None})
        assert invite.status_code==201,invite.text
        token=invite.json()["token"]
        staff=TestClient(main.app)
        result=post(staff,"/api/invitations/accept",{"token":token,"password":password})
        assert result.status_code==201,result.text

def inspect(playwright,role):
    email=(slug if role=="school_admin" else role+"-"+slug)+"@example.test"
    browser=playwright.chromium.launch(headless=True)
    context=browser.new_context(viewport={"width":390,"height":844})
    page=context.new_page()
    page.goto(BASE,wait_until="networkidle")
    page.locator("#school-slug").fill(slug)
    page.locator("#login-email").fill(email)
    page.locator("#login-password").fill(password)
    page.locator("#login button[type=submit], #login button").first.click()
    page.locator("#app-shell:not([hidden])").wait_for(timeout=15000)
    visible=lambda key:page.locator(f'#nav [data-go="{key}"]').count()>0
    assert visible("incidents"),f"{role} cannot reach incidents"
    assert visible("learners"),f"{role} cannot reach learners"
    assert visible("security"),f"{role} cannot configure own MFA"
    if role=="educator":
        assert not visible("cases")
        assert not visible("billing")
        assert not visible("staff")
        page.locator('#nav [data-go="incidents"]').click()
        page.get_by_role("heading",name="Incidents",exact=True).wait_for(timeout=12000)
        page.get_by_role("button",name="Report incident").click()
        page.get_by_role("heading",name="Quick incident report").wait_for()
        page.get_by_role("button",name="Cancel").click()
    else:
        assert visible("cases"),f"{role} should have case access"
        assert visible("hearings"),f"{role} should have hearing access"
        assert visible("billing")==(role in ("school_admin","principal"))
        page.locator('#nav [data-go="cases"]').click()
        page.get_by_role("heading",name="Cases",exact=True).wait_for(timeout=12000)
    assert "Unable to load page" not in page.locator("#page").inner_text()
    context.close();browser.close()

if __name__=="__main__":
    seed()
    with sync_playwright() as playwright:
        for role in ("educator","hod","smt","principal","school_admin"):
            inspect(playwright,role)
