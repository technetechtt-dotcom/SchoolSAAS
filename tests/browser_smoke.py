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
    browser=playwright.chromium.launch(headless=True)
    page=browser.new_page(viewport={"width":1280,"height":800})
    page.goto(url,wait_until="networkidle")
    page.locator("#school-name").fill("Fictional Browser School")
    page.locator("#new-slug").fill(slug)
    page.locator("#reg-email").fill(slug+"@example.test")
    page.locator("#reg-password").fill("fictional-password-for-testing")
    page.locator("#register button").click()
    page.locator("#app-shell:not([hidden])").wait_for(timeout=15000)
    page.locator('[data-go="learners"]').click()
    page.get_by_role("heading",name="Learners").wait_for()
    page.get_by_role("button",name="Add learner").click()
    page.locator('#dialog input[name="admission_no"]').fill("TEST-001")
    page.locator('#dialog input[name="first_name"]').fill("Demo")
    page.locator('#dialog input[name="surname"]').fill("Student")
    page.locator('#dialog input[name="grade"]').fill("5")
    page.locator('#dialog input[name="class_name"]').fill("5A")
    page.locator('#dialog button[type="submit"]').click()
    page.get_by_role("button",name="Demo Student").wait_for(timeout=15000)
    page.set_viewport_size({"width":390,"height":844})
    page.locator("#menu-toggle").click()
    assert page.locator("#sidebar").evaluate("(node)=>node.classList.contains('open')")
    page.get_by_role("button",name="Sign out").click()
    page.locator("#login-screen:not([hidden])").wait_for()
    browser.close()
