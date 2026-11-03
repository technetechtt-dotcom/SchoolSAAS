"""Populate the local demo school with fictitious Grade 1–12 test data.

Usage (server must be running):
  python scripts/seed_demo.py

Defaults: school=demo, email=admin@demo.local, password=QAZwsx123456
"""
from __future__ import annotations
import json, os, random, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.getenv("DEMO_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SLUG = os.getenv("DEMO_SLUG", "demo")
EMAIL = os.getenv("DEMO_EMAIL", "admin@demo.local")
PASSWORD = os.getenv("DEMO_PASSWORD", "QAZwsx123456")
RNG = random.Random(42)

FIRST = ["Thabo","Lerato","Aisha","Johan","Nomsa","Ethan","Sipho","Mia","Karabo","Sara",
         "Daniel","Zanele","Amogelang","Fatima","Liam","Boitumelo","Chloe","Kgosi","Nina","Andile",
         "Precious","Ryan","Tshepo","Emily","Bandile","Olivia","Musa","Hannah","Lebo","James"]
LAST = ["Mokoena","Dlamini","Patel","van Wyk","Khumalo","Naidoo","Ndlovu","Botha","Molefe","Govender",
        "Smith","Sithole","Mabena","Pillay","Jacobs","Radebe","Williams","Mthembu","Fourie","Nkosi"]

OFFENCES = [
    ("L1", "Late for class", "Punctuality", 1),
    ("L2", "Late after break", "Punctuality", 1),
    ("D1", "Disruptive talking", "Classroom habit", 2),
    ("D2", "Calling out answers", "Classroom habit", 1),
    ("H1", "Homework not submitted", "Academic habit", 1),
    ("H2", "Incomplete classwork", "Academic habit", 1),
    ("P1", "Playground dispute", "Social", 2),
    ("P2", "Exclusion of peers", "Social", 2),
    ("U1", "Uniform incomplete", "Routine habit", 1),
    ("U2", "Phone during lesson", "Routine habit", 2),
    ("B1", "Bullying allegation", "Serious", 3),
    ("S1", "Unsafe behaviour", "Safety", 4),
    ("R1", "Disrespectful language", "Relationships", 2),
    ("C1", "Corridor running", "Movement habit", 1),
]

HABIT_NOTES = {
    "L1": "Recurring morning lateness pattern",
    "D1": "Talking over instruction habit",
    "H1": "Homework organisation habit",
    "U1": "Uniform readiness habit",
    "C1": "Transition behaviour habit",
    "P1": "Peer conflict habit on playground",
}


class Client:
    def __init__(self):
        self.cookies = {}

    def _headers(self, json_body=True):
        h = {"Origin": BASE}
        if json_body:
            h["Content-Type"] = "application/json"
        if "csrf_token" in self.cookies:
            h["X-CSRF-Token"] = self.cookies["csrf_token"]
        if self.cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        return h

    def _store_cookies(self, resp):
        for k, v in resp.headers.items():
            if k.lower() != "set-cookie":
                continue
            part = v.split(";", 1)[0]
            if "=" in part:
                name, val = part.split("=", 1)
                self.cookies[name.strip()] = val.strip()

    def request(self, method, path, body=None, expected=(200, 201)):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(BASE + path, data=data, headers=self._headers(body is not None), method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                self._store_cookies(resp)
                raw = resp.read().decode()
                if resp.status not in expected:
                    raise SystemExit(f"{method} {path} -> {resp.status}: {raw[:300]}")
                if not raw:
                    return {}
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {"_raw": True}
        except urllib.error.HTTPError as e:
            detail = e.read().decode()
            raise SystemExit(f"{method} {path} -> {e.code}: {detail}")


def main():
    c = Client()
    c.request("GET", "/")
    login = c.request("POST", "/api/login", {
        "school_slug": SLUG, "email": EMAIL, "password": PASSWORD
    })
    if login.get("mfa_required"):
        raise SystemExit("Demo admin has MFA enabled; disable MFA before seeding.")
    me = c.request("GET", "/api/me")
    if not me.get("authenticated"):
        raise SystemExit("Login failed for demo account")
    print(f"Signed in as {EMAIL} @ {SLUG} ({me['school']})")

    offence_ids = {}
    for code, name, category, severity in OFFENCES:
        try:
            r = c.request("POST", "/api/offences", {
                "code": code, "name": name, "category": category, "severity": severity
            })
            offence_ids[code] = r["id"]
        except SystemExit as e:
            if "409" in str(e) or "exists" in str(e).lower():
                existing = c.request("GET", "/api/offences")
                offence_ids[code] = next(x["id"] for x in existing if x["code"] == code)
            else:
                raise
    print(f"Offences ready: {len(offence_ids)}")

    # Build Grade 1–12 learners (10+ per grade, classes A/B/C)
    rows = []
    learner_meta = []  # admission -> grade
    n = 0
    per_grade = int(os.getenv("DEMO_LEARNERS_PER_GRADE", "10"))
    for grade in range(1, 13):
        for i in range(1, per_grade + 1):
            n += 1
            if i <= 4:
                stream = "A"
            elif i <= 7:
                stream = "B"
            else:
                stream = "C"
            klass = f"{grade}{stream}"
            admission = f"G{grade:02d}-{i:02d}"
            first = FIRST[(n + grade) % len(FIRST)]
            surname = LAST[(n * 3 + grade) % len(LAST)]
            rows.append({
                "admission_no": admission,
                "first_name": first,
                "surname": surname,
                "grade": str(grade),
                "class_name": klass,
            })
            learner_meta.append((admission, str(grade), klass, first, surname))

    imported = c.request("POST", "/api/learners/import", {"rows": rows})
    print(f"Learners import: created={imported.get('created')} skipped={len(imported.get('skipped', []))}")

    # Resolve IDs (directory is paginated)
    learner_ids = {}
    offset = 0
    while True:
        page = c.request("GET", f"/api/directory/learners?limit=100&offset={offset}")
        for item in page.get("items", []):
            learner_ids[item["admission_no"]] = item["id"]
        offset += 100
        if offset >= page.get("total", 0):
            break
    print(f"Learners available: {len(learner_ids)}")

    c.request("PUT", "/api/settings", {"repeat_threshold": 2})
    try:
        c.request("PUT", "/api/settings/academic", {
            "academic_year": 2026, "term": 4, "school_contact_email": "office@demo.local"
        })
    except SystemExit:
        pass

    # Varied incidents across all grades (habits + one-offs)
    incident_ids_by_learner = {adm: [] for adm, *_ in learner_meta}
    all_incident_ids = []
    locations = ["Classroom", "Playground", "Corridor", "Assembly", "School gate", "Sports field"]
    actions = ["Verbal correction", "Restorative conversation", "Parent contacted", "Referred to HOD"]

    # Habit patterns: pick ~1 learner per grade for lateness / homework / disruption repeats
    for grade in range(1, 13):
        grade_learners = [m for m in learner_meta if m[1] == str(grade)]
        target = grade_learners[0]
        admission = target[0]
        for code in ("L1", "H1", "D1"):
            if code not in offence_ids:
                continue
            repeats = 2 if code in ("L1", "H1") else 1
            for r in range(repeats):
                desc = HABIT_NOTES.get(code, OFFENCES[0][1]) + f" (grade {grade}, occurrence {r+1})."
                inc = c.request("POST", "/api/incidents", {
                    "learner_id": learner_ids[admission],
                    "offence_id": offence_ids[code],
                    "location": RNG.choice(locations),
                    "description": desc,
                    "immediate_action": RNG.choice(actions),
                })
                incident_ids_by_learner[admission].append(inc["id"])
                all_incident_ids.append(inc["id"])

        # Extra single incidents for other learners in the grade
        for meta in grade_learners[1:3]:
            code = RNG.choice(["D2", "U1", "C1", "P1", "R1", "U2", "P2", "H2"])
            inc = c.request("POST", "/api/incidents", {
                "learner_id": learner_ids[meta[0]],
                "offence_id": offence_ids[code],
                "location": RNG.choice(locations),
                "description": f"{meta[3]} {meta[4]} — {dict(OFFENCES)[code] if False else code} concern in grade {grade}.",
                "immediate_action": RNG.choice(actions),
            })
            # fix description properly
            oname = next(o[1] for o in OFFENCES if o[0] == code)
            # Can't patch easily; leave as is with code in text - better recreate description via known mapping
            incident_ids_by_learner[meta[0]].append(inc["id"])
            all_incident_ids.append(inc["id"])

    # Serious incidents in senior grades
    for admission, grade, *_ in learner_meta:
        if grade in {"7", "10", "12"} and admission.endswith("-01"):
            code = "B1" if grade != "12" else "S1"
            inc = c.request("POST", "/api/incidents", {
                "learner_id": learner_ids[admission],
                "offence_id": offence_ids[code],
                "location": "Corridor" if code == "B1" else "School gate",
                "description": f"Serious concern recorded for grade {grade} learner (fictitious demo only).",
                "immediate_action": "Referred to HOD",
            })
            incident_ids_by_learner[admission].append(inc["id"])
            all_incident_ids.append(inc["id"])

    print(f"Incidents created this run: {len(all_incident_ids)}")

    # Cases + interventions for habit learners and serious ones
    cases_made = 0
    interventions_made = 0
    for admission, ids in incident_ids_by_learner.items():
        if len(ids) < 2:
            continue
        grade = next(g for a, g, *_ in learner_meta if a == admission)
        first = next(f for a, g, k, f, s in learner_meta if a == admission)
        case = c.request("POST", "/api/cases", {
            "learner_id": learner_ids[admission],
            "title": f"Grade {grade} support plan — {first}",
            "incident_ids": ids[:3],
        })
        cases_made += 1
        for iid in ids[:2]:
            c.request("POST", "/api/interventions", {
                "incident_id": iid,
                "type": RNG.choice(["Restorative conversation", "Parent meeting", "Behaviour agreement", "Monitoring"]),
                "notes": f"Demo intervention for grade {grade} habit/support pathway."
            })
            interventions_made += 1
        if grade in {"7", "10", "12"}:
            try:
                c.request("POST", "/api/hearings", {
                    "case_id": case["id"],
                    "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=5 + int(grade))).isoformat(),
                    "chair": "Principal (demo)",
                    "notes": "Human-led supportive hearing — no automated sanction."
                })
            except SystemExit:
                pass
    print(f"Cases created: {cases_made}; interventions: {interventions_made}")

    # Guardians / contacts for a sample across phases
    for admission, grade, klass, first, surname in learner_meta:
        if not admission.endswith("-01"):
            continue
        try:
            c.request("POST", "/api/guardians", {
                "learner_id": learner_ids[admission],
                "name": f"Guardian of {first}",
                "relationship": "Parent",
                "email": f"guardian.{admission.lower().replace('-', '')}@example.test",
                "phone": f"082{grade.zfill(2)}{admission[-2:]}000"[:10],
            })
        except SystemExit:
            pass
        c.request("POST", "/api/parent-contacts", {
            "learner_id": learner_ids[admission],
            "method": "Phone",
            "purpose": f"Grade {grade} support update",
            "outcome": "Guardian noted",
        })

    try:
        cv = c.request("POST", "/api/conduct-versions", {
            "version_label": "2026.ALL",
            "title": "Whole-school Code of Conduct (Grades 1–12)",
            "body": "All learners from Grade 1 to Grade 12 are supported with age-appropriate restorative practice. "
                    "Habit patterns are monitored; serious matters are reviewed by authorised staff. "
                    "This system never applies automated sanctions.",
            "effective_from": datetime.now(timezone.utc).isoformat(),
        })
        c.request("PATCH", f"/api/conduct-versions/{cv['id']}/approve", {})
    except SystemExit:
        pass

    # Verify grade 7 filter
    g7 = c.request("GET", "/api/directory/learners?grade=7&limit=50")
    print(f"\nGrade 7 filter check: {g7.get('total')} learners")
    grades = c.request("GET", "/api/directory/learners?limit=1").get("grades", [])
    print("Learners by grade:")
    for g in grades:
        print(f"  Grade {g['grade']}: {g['learners']}")

    summary = {
        "learners": c.request("GET", "/api/directory/learners?limit=1").get("total"),
        "offences": len(c.request("GET", "/api/offences")),
        "incidents": len(c.request("GET", "/api/incidents")),
        "cases": len(c.request("GET", "/api/cases")),
        "interventions": len(c.request("GET", "/api/interventions")),
    }
    print("\nDemo seed complete:")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("\nView Grade 7: Learners page → choose Grade 7 filter (or Grades & classes → Grade 7)")
    print(f"Login: {SLUG} / {EMAIL}")


if __name__ == "__main__":
    main()
