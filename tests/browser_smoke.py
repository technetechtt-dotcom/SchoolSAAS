"""Run with a local SchoolSAAS server and Playwright Chromium installed.

Example: JWT_SECRET=example uvicorn app.main:app --port 8000
Then: SCHOOLCARE_URL=http://127.0.0.1:8000 python tests/browser_smoke.py
"""
import os
from uuid import uuid4
from playwright.sync_api import sync_playwright

url=os.getenv("SCHOOLCARE_URL","http://127.0.0.1:8000")
slug="browser-"+uuid4().hex[:12]
with sync_playwright() as playwright:
    engine=os.getenv("BROWSER_ENGINE","chromium")
    browser=getattr(playwright,engine).launch(headless=True)
    page=browser.new_page(viewport={"width":1280,"height":800})
    page.on("pageerror", lambda error: print("BROWSER JAVASCRIPT ERROR:", str(error), flush=True))
    page.on("console", lambda message: print("BROWSER CONSOLE:",message.text,flush=True) if message.type=="error" else None)
    page.goto(url,wait_until="networkidle")
    page.locator("#school-name").fill("Fictional Browser School")
    page.locator("#new-slug").fill(slug)
    page.locator("#reg-email").fill(slug+"@example.test")
    page.locator("#reg-password").fill("fictional-password-for-testing")
    page.locator("#register button").click()
    page.locator("#app-shell:not([hidden])").wait_for(timeout=15000)
    page.locator('[data-go="learners"]').click()
    page.wait_for_timeout(1500)
    if not page.get_by_role("heading",name="Learners",exact=True).is_visible():
        raise AssertionError("Learner navigation failed; URL="+page.url+"; page="+page.locator("#page").inner_text()[:2500])
    page.get_by_role("button",name="Add learner").click()
    page.locator('#dialog input[name="first_name"]').fill("Demo")
    page.locator('#dialog input[name="surname"]').fill("Student")
    page.locator('#dialog input[name="grade"]').fill("5")
    page.locator('#dialog input[name="class_name"]').fill("5A")
    page.locator('#dialog button[type="submit"]').click()
    page.get_by_role("button",name="Demo Student").wait_for(timeout=15000)
    # Check representative administrator pages with a real browser session.
    for route,title in [
        ("incidents","Incidents"),("cases","Cases"),
        ("hearings","Disciplinary hearings"),("evidence","Evidence files"),
        ("reports","Reports"),("staff","Staff & access"),
        ("settings","School settings"),("security","Security & MFA"),
        ("privacy","Privacy & retention"),("billing","Billing")
    ]:
        page.locator(f'#nav [data-go="{route}"]').click()
        page.get_by_role("heading",name=title,exact=True).wait_for(timeout=10000)
        assert "Unable to load page" not in page.locator("#page").inner_text()
    page.locator('#nav [data-go="learners"]').click()
    page.get_by_role("heading",name="Learners",exact=True).wait_for(timeout=10000)
    page.set_viewport_size({"width":390,"height":844})
    page.locator("#menu-toggle").click()
    assert page.locator("#sidebar").evaluate("(node)=>node.classList.contains('open')")
    page.locator("#menu-toggle").click()
    assert not page.locator("#sidebar").evaluate("(node)=>node.classList.contains('open')")
    page.get_by_role("button",name="Sign out").click()
    page.locator("#login-screen:not([hidden])").wait_for()
    browser.close()
