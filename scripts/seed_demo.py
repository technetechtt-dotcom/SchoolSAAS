"""Populate the local demo school with Venus LDMS–style fictitious data.

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
         "Daniel","Zanele","Amogelang","Fatima","Liam","Boitumelo","Chloe","Kgosi","Nina","Andile"]
LAST = ["Mokoena","Dlamini","Patel","van Wyk","Khumalo","Naidoo","Ndlovu","Botha","Molefe","Govender",
        "Smith","Sithole","Mabena","Pillay","Jacobs","Radebe","Williams","Mthembu","Fourie","Nkosi"]

# Venus-style catalogue: code, name, category, severity, escalate_hod, escalate_smt, similarity_group, repeat_threshold
OFFENCES = [
    ("B001", "Minor classroom disruption", "Behaviour", 1, False, False, "disruption", 3),
    ("B002", "Persistent classroom disruption", "Behaviour", 2, True, False, "disruption", 2),
    ("B003", "Failure to follow instruction", "Defiance", 1, False, False, "defiance", 3),
    ("B004", "Persistent defiance", "Defiance", 2, True, False, "defiance", 2),
    ("B005", "Bullying behaviour", "Bullying", 2, True, True, "bullying", 1),
    ("A001", "Physical aggression / fighting", "Fighting/Aggression", 3, True, True, "aggression", 1),
    ("T001", "Threatening behaviour", "Threats/Intimidation", 3, True, True, "threats", 1),
    ("P001", "Minor vandalism / property misuse", "Property", 2, True, False, "property", 2),
    ("S001", "Leaving class without permission", "Safety", 2, True, False, "safety", 2),
    ("S002", "Serious intimidation", "Safety", 4, True, True, "threats", 1),
    ("L001", "Late for class", "Punctuality", 1, False, False, "punctuality", 3),
    ("H001", "Homework not submitted", "Academic habit", 1, False, False, "homework", 3),
    ("U001", "Uniform incomplete", "Routine habit", 1, False, False, "uniform", 3),
    ("C001", "Corridor running", "Movement habit", 1, False, False, "movement", 3),
]

LOCATIONS = ["Classroom", "Playground", "Corridor", "Toilet", "Assembly area", "Sports field", "School gate"]
ACTIONS = ["Verbal correction", "Restorative conversation", "Learner referred to HOD", "Parent contacted", "Other"]


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


def ensure_offence(c, row):
    code, name, category, severity, hod, smt, group, thresh = row
    payload = {
        "code": code, "name": name, "category": category, "severity": severity,
        "escalate_hod": hod, "escalate_smt": smt, "similarity_group": group, "repeat_threshold": thresh,
    }
    try:
        return c.request("POST", "/api/offences", payload)["id"]
    except SystemExit as e:
        if "409" not in str(e):
            raise
        existing = c.request("GET", "/api/offences")
        return next(x["id"] for x in existing if x["code"] == code)


def _obs(c, lid, grade, when, domain, title, summary, level, factor, score=None, source="classroom_observation"):
    body = {
        "learner_id": lid,
        "observed_at": when.isoformat(),
        "grade_at_time": str(grade),
        "domain": domain,
        "title": title,
        "summary": summary,
        "level": level,
        "contributing_factor": factor,
        "source": source,
    }
    if score is not None:
        body["score"] = score
    c.request("POST", f"/api/learners/{lid}/observations", body)


def seed_learner_journeys(c, learner_ids, learner_meta):
    """Build Grade-1→now stories for spotlight learners (reading / counting / EQ + school vs home)."""
    count = 0
    # Spotlight: G07-01 (habit + literacy struggle), G04-01 (numeracy), G10-01 (EQ + home stress), G01-02 (strong start)
    stories = {
        "G07-01": {
            "enrolled_on": "2019-01-15",
            "grade_started": "1",
            "path": [
                (1, -6.5, "reading", "Letter sounds emerging slowly",
                 "Struggles to blend CVC words; teacher notes limited print exposure at home.", "concern", "both"),
                (1, -6.2, "numeracy", "Counts to 10 with fingers",
                 "One-to-one correspondence insecure beyond 10.", "emerging", "school"),
                (1, -5.8, "emotional_eq", "Withdraws when corrected",
                 "Avoids eye contact after classroom correction; peers tease quietly.", "concern", "school"),
                (1, -5.5, "home_factor", "Irregular bedtime / homework help",
                 "Guardian reports shift work; homework often unfinished.", "concern", "home"),
                (2, -5.0, "reading", "Sight words improving with small group",
                 "School reading club 2× week; still below grade peers.", "developing", "school"),
                (2, -4.7, "numeracy", "Number bonds to 10 still shaky",
                 "Concrete materials help; abstract worksheets overwhelm.", "emerging", "school"),
                (3, -3.8, "emotional_eq", "Uses calm-down corner when frustrated",
                 "EQ coaching with counsellor — names feelings more often.", "developing", "school"),
                (3, -3.5, "reading", "Reads short sentences with support",
                 "Phonics catch-up; home reading log started with grandmother.", "developing", "both"),
                (4, -2.6, "numeracy", "Place value confusion persists",
                 "Cannot reliably count past 100; skips decades.", "concern", "school"),
                (5, -1.8, "reading", "Fluency still below grade expectation",
                 "Comprehension stronger orally than in print.", "emerging", "both"),
                (5, -1.5, "cognitive_assessment", "Learning support screening (demo)",
                 "Qualified assessor note on file — working memory concern; NOT a clinical IQ diagnosis by the school.",
                 "concern", "school", 88.0, "assessment"),
                (6, -0.9, "emotional_eq", "Peer conflict after playground incidents",
                 "Behaviour incidents rise when literacy tasks feel shameful.", "concern", "both"),
                (7, -0.2, "reading", "Still cannot read independently for classwork",
                 "Ask: school instruction gap, home literacy environment, or unresolved learning need?",
                 "concern", "both"),
                (7, -0.1, "school_factor", "Large class / limited remedial slots",
                 "Remedial reading waitlist — only 1 period/week available.", "concern", "school"),
            ],
        },
        "G04-01": {
            "enrolled_on": "2022-01-20",
            "grade_started": "1",
            "path": [
                (1, -3.4, "numeracy", "Cannot count reliably past 5",
                 "Confuses number names; counting songs help briefly.", "concern", "school"),
                (1, -3.2, "reading", "Recognises own name in print",
                 "Letter recognition on track for Grade 1.", "developing", "school"),
                (1, -3.0, "home_factor", "No counting games at home",
                 "Family prefers oral storytelling; few number toys.", "emerging", "home"),
                (2, -2.4, "numeracy", "Uses counters for sums to 10",
                 "Progress with concrete objects; still cannot skip-count.", "developing", "school"),
                (2, -2.2, "emotional_eq", "Maths anxiety — tears in timed drills",
                 "Timed tests trigger shutdown; untimed practice succeeds.", "concern", "school"),
                (3, -1.3, "numeracy", "Place value emerging with base-ten blocks",
                 "Teacher notes improvement when home practice pack used.", "developing", "both"),
                (4, -0.3, "numeracy", "Still cannot count fluently past 50",
                 "Ask: instructional gap at school or limited home number talk?", "concern", "both"),
                (4, -0.2, "emotional_eq", "Pride when peer tutors celebrate wins",
                 "Buddy system reduced anxiety; smiles during number games.", "strength", "school"),
            ],
        },
        "G10-01": {
            "enrolled_on": "2016-01-18",
            "grade_started": "1",
            "path": [
                (1, -9.5, "emotional_eq", "Warm, curious Grade 1 starter",
                 "Settled well; shares toys; seeks help appropriately.", "strength", "school"),
                (1, -9.2, "reading", "Early reader — above peers",
                 "Decodable books finished quickly.", "secure", "both"),
                (3, -7.0, "home_factor", "Family relocation stress",
                 "Moved town mid-year; sleep disrupted for a term.", "concern", "home"),
                (4, -6.0, "emotional_eq", "Sudden anger outbursts",
                 "Classroom meltdowns after weekend visits to separated parent.", "concern", "home"),
                (5, -5.0, "reading", "Reading dips when attendance irregular",
                 "Missed phonics units during travel between homes.", "emerging", "both"),
                (7, -3.0, "emotional_eq", "Peer leadership returns with counselling",
                 "School counsellor + parent agreement on consistent routines.", "developing", "both"),
                (8, -2.0, "cognitive_assessment", "Optional EQ inventory (demo)",
                 "Support team EQ checklist score recorded from qualified facilitator — not a clinical diagnosis.",
                 "developing", "school", 102.0, "assessment"),
                (9, -1.0, "social", "Mentors younger readers",
                 "Strength rebuilt — uses literacy strength to restore belonging.", "strength", "school"),
                (10, -0.2, "emotional_eq", "Conflict when home conflict spikes",
                 "Ask: school social dynamics or unresolved home stress?", "concern", "home"),
            ],
        },
        "G01-02": {
            "enrolled_on": "2026-01-14",
            "grade_started": "1",
            "path": [
                (1, -0.4, "reading", "Enjoys picture walks",
                 "Retells stories; letter play strong.", "secure", "school"),
                (1, -0.3, "numeracy", "Counts classroom objects to 20",
                 "Solid one-to-one; beginning to write numerals.", "secure", "school"),
                (1, -0.2, "emotional_eq", "Seeks help calmly",
                 "Names feelings; recovers quickly after disappointment.", "strength", "both"),
                (1, -0.1, "home_factor", "Daily story and counting rhymes",
                 "Guardian reads nightly; kitchen counting games.", "strength", "home"),
            ],
        },
    }
    for admission, story in stories.items():
        lid = learner_ids.get(admission)
        if not lid:
            continue
        try:
            c.request("PATCH", f"/api/learners/{lid}/enrolment", {
                "enrolled_on": story["enrolled_on"],
                "grade_started": story["grade_started"],
            })
        except SystemExit as e:
            print(f"Enrolment patch {admission}: {e}")
        # Skip if journey already has observations (re-seed safe-ish)
        existing = c.request("GET", f"/api/learners/{lid}/journey")
        if existing.get("observations"):
            print(f"Journey already present for {admission} — skipping reseed")
            continue
        for row in story["path"]:
            grade, years_ago, domain, title, summary, level, factor = row[:7]
            score = row[7] if len(row) > 7 else None
            source = row[8] if len(row) > 8 else "classroom_observation"
            when = datetime.now(timezone.utc) + timedelta(days=int(years_ago * 365))
            _obs(c, lid, grade, when, domain, title, summary, level, factor, score, source)
            count += 1
        # Light enrolment on other -01 learners without full stories
    for admission, grade, *_ in learner_meta:
        if not admission.endswith("-01") or admission in stories:
            continue
        lid = learner_ids.get(admission)
        if not lid:
            continue
        try:
            start_year = 2026 - max(0, int(grade) - 1)
            c.request("PATCH", f"/api/learners/{lid}/enrolment", {
                "enrolled_on": f"{start_year}-01-15",
                "grade_started": "1",
            })
        except SystemExit:
            pass
    return count


def main():
    c = Client()
    c.request("GET", "/")
    login = c.request("POST", "/api/login", {"school_slug": SLUG, "email": EMAIL, "password": PASSWORD})
    if login.get("mfa_required"):
        raise SystemExit("Demo admin has MFA enabled; disable MFA before seeding.")
    me = c.request("GET", "/api/me")
    if not me.get("authenticated"):
        raise SystemExit("Login failed for demo account")
    print(f"Signed in as {EMAIL} @ {SLUG} ({me['school']})")

    c.request("PUT", "/api/settings", {
        "repeat_threshold": 2,
        "repeat_window_days": 90,
        "repeat_similar_threshold": 2,
        "repeat_total_threshold": 5,
        "follow_up_default_days": 7,
        "incident_prefix": "INC",
        "case_prefix": "CASE",
        "admission_prefix": "VPS",
    })
    try:
        c.request("PUT", "/api/settings/academic", {
            "academic_year": 2026, "term": 3, "school_contact_email": "office@demo.local"
        })
    except SystemExit:
        pass

    offence_ids = {row[0]: ensure_offence(c, row) for row in OFFENCES}
    print(f"Offences ready: {len(offence_ids)}")

    per_grade = int(os.getenv("DEMO_LEARNERS_PER_GRADE", "10"))
    rows, learner_meta, n = [], [], 0
    for grade in range(1, 13):
        for i in range(1, per_grade + 1):
            n += 1
            stream = "A" if i <= 4 else ("B" if i <= 7 else "C")
            klass = f"{grade}{stream}"
            admission = f"G{grade:02d}-{i:02d}"
            first = FIRST[(n + grade) % len(FIRST)]
            surname = LAST[(n * 3 + grade) % len(LAST)]
            rows.append({"admission_no": admission, "first_name": first, "surname": surname,
                         "grade": str(grade), "class_name": klass})
            learner_meta.append((admission, str(grade), klass, first, surname))
    imported = c.request("POST", "/api/learners/import", {"rows": rows})
    print(f"Learners import: created={imported.get('created')} skipped={len(imported.get('skipped', []))}")

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

    incident_ids_by_learner = {adm: [] for adm, *_ in learner_meta}
    all_incident_ids = []

    # Habit / repeat patterns + hotspot concentration (Playground / Corridor)
    for grade in range(1, 13):
        grade_learners = [m for m in learner_meta if m[1] == str(grade)]
        target = grade_learners[0]
        for code, repeats in (("L001", 3), ("H001", 2), ("B001", 2)):
            for r in range(repeats):
                loc = "Classroom" if code != "B001" else RNG.choice(["Playground", "Corridor", "Classroom"])
                inc = c.request("POST", "/api/incidents", {
                    "learner_id": learner_ids[target[0]],
                    "offence_id": offence_ids[code],
                    "location": loc,
                    "description": f"Demo pattern {code} for grade {grade} (occurrence {r+1}). Fictitious only.",
                    "immediate_action": RNG.choice(ACTIONS),
                })
                incident_ids_by_learner[target[0]].append(inc["id"])
                all_incident_ids.append(inc["id"])
        for meta in grade_learners[1:4]:
            code = RNG.choice(["B003", "U001", "C001", "B001", "S001", "P001"])
            loc = RNG.choice(["Playground", "Corridor", "Classroom", "Assembly area"])
            oname = next(o[1] for o in OFFENCES if o[0] == code)
            inc = c.request("POST", "/api/incidents", {
                "learner_id": learner_ids[meta[0]],
                "offence_id": offence_ids[code],
                "location": loc,
                "description": f"{meta[3]} {meta[4]} — {oname} concern in grade {grade} (demo).",
                "immediate_action": RNG.choice(ACTIONS),
            })
            incident_ids_by_learner[meta[0]].append(inc["id"])
            all_incident_ids.append(inc["id"])

    # Serious / SMT-flagged demo incidents
    for admission, grade, *_ in learner_meta:
        if grade in {"6", "7", "10", "12"} and admission.endswith("-01"):
            code = "A001" if grade in {"6", "7"} else ("B005" if grade == "10" else "T001")
            inc = c.request("POST", "/api/incidents", {
                "learner_id": learner_ids[admission],
                "offence_id": offence_ids[code],
                "location": "Playground" if code == "A001" else "Corridor",
                "description": f"Serious demo concern for grade {grade}. Review required — no automated sanction.",
                "immediate_action": "Learner referred to HOD",
            })
            incident_ids_by_learner[admission].append(inc["id"])
            all_incident_ids.append(inc["id"])
    print(f"Incidents created this run: {len(all_incident_ids)}")

    cases_made = interventions_made = 0
    overdue_due = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    future_due = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
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
        for idx, iid in enumerate(ids[:2]):
            c.request("POST", "/api/interventions", {
                "incident_id": iid,
                "type": RNG.choice(["Restorative conversation", "Parent meeting", "Behaviour agreement", "Monitoring", "HOD discussion"]),
                "notes": f"Demo intervention for grade {grade} progressive support pathway.",
                "due_at": overdue_due if idx == 0 and grade in {"5", "7", "10"} else future_due,
            })
            interventions_made += 1
    print(f"Cases created: {cases_made}; interventions: {interventions_made}")

    # Parent contacts, guardians, overdue meetings, letters
    for admission, grade, klass, first, surname in learner_meta:
        if not admission.endswith("-01"):
            continue
        lid = learner_ids[admission]
        try:
            c.request("POST", "/api/guardians", {
                "learner_id": lid, "name": f"Guardian of {first}", "relationship": "Parent",
                "email": f"guardian.{admission.lower().replace('-', '')}@example.test",
                "phone": f"082{grade.zfill(2)}{admission[-2:]}00"[:10],
            })
        except SystemExit:
            pass
        c.request("POST", "/api/parent-contacts", {
            "learner_id": lid, "method": "Phone",
            "purpose": f"Grade {grade} behaviour concern notification",
            "outcome": "Spoke — follow-up arranged",
        })
        try:
            c.request("POST", "/api/appointments", {
                "learner_id": lid,
                "title": f"Parent meeting — {first} {surname}",
                "scheduled_at": (datetime.now(timezone.utc) - timedelta(days=2 if grade in {"7", "10"} else -5)).isoformat(),
            })
        except SystemExit:
            pass

    try:
        c.request("POST", "/api/letter-templates", {
            "code": "PARENT_MEETING",
            "name": "Parent meeting request",
            "body": "Dear Parent/Guardian,\n\nWe request a meeting regarding {{learner_name}} ({{grade}} {{class_name}}).\nSchool: {{school_name}}\nPlease contact the office to confirm.\n\nKind regards",
        })
        c.request("POST", "/api/letter-templates", {
            "code": "BEHAVIOUR_NOTICE",
            "name": "Behaviour concern notification",
            "body": "Dear Parent/Guardian,\n\nThis notice concerns {{learner_name}} (admission {{admission_no}}).\nWe are recording supportive interventions — not automated sanctions.\nSchool: {{school_name}}\n\nKind regards",
        })
    except SystemExit:
        pass

    try:
        cv = c.request("POST", "/api/conduct-versions", {
            "version_label": "2026.VPS",
            "title": "Code of Conduct — progressive discipline (demo)",
            "body": "Venus-style progressive discipline: capture once, intervene early, escalate for review. "
                    "The system never imposes punishment from points or scores. Authorised structures decide outcomes.",
            "effective_from": datetime.now(timezone.utc).isoformat(),
        })
        c.request("PATCH", f"/api/conduct-versions/{cv['id']}/approve", {})
    except SystemExit:
        pass

    # Demo staff invites (token printed when SMTP off)
    for role, email in (("educator", "educator@demo.local"), ("hod", "hod@demo.local"), ("smt", "smt@demo.local")):
        try:
            inv = c.request("POST", "/api/invitations", {
                "email": email, "role": role, "assigned_class": "7A" if role == "educator" else None
            })
            if inv.get("token"):
                print(f"Invite {role} {email}: token={inv['token'][:18]}… (accept in UI or leave unused)")
        except SystemExit as e:
            print(f"Invite {email} skipped: {e}")

    # Longitudinal journey: Grade 1 → current (reading / numeracy / EQ + school vs home)
    journey_seeded = seed_learner_journeys(c, learner_ids, learner_meta)
    print(f"Learner journey observations: {journey_seeded}")

    warn = c.request("GET", "/api/analytics/early-warning")
    hot = c.request("GET", "/api/analytics/hotspots")
    reps = c.request("GET", "/api/analytics/repeats")
    g7 = c.request("GET", "/api/directory/learners?grade=7&limit=50")
    print(f"\nGrade 7 learners: {g7.get('total')}")
    print(f"Early warning: overdue interventions={warn['counts']['overdue_interventions']}, "
          f"overdue meetings={warn['counts']['overdue_appointments']}, "
          f"serious={warn['counts']['serious_open']}, open reviews={warn['counts']['open_reviews']}")
    print(f"Hotspot top locations: {list((hot.get('by_location') or {}).items())[:4]}")
    print(f"Repeat board rows: {len(reps.get('items') or [])}")
    print("\nDemo seed complete for Venus LDMS story.")
    print(f"Login: {SLUG} / {EMAIL} / {PASSWORD}")
    print("Open Overview for early warning + hotspots; Learners → profile for discipline + lifelong journey "
          "(reading/numeracy/EQ, school vs home); What do I do? for process guide.")


if __name__ == "__main__":
    main()
