"""Automatic intervention recommendations from behaviour, EQ, IQ and incidents.

Advisory only — staff decide. Never invents IQ/EQ scores or clinical diagnoses.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from collections import Counter
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import main as m
from app.learner_journey import LearnerObservation, DOMAINS

router = APIRouter(prefix="/api")
MANAGERS = ("school_admin", "principal", "smt", "hod")
CONCERN_LEVELS = {"concern", "emerging"}

# Catalogue of recommendable intervention types (aligned with create-intervention UI + extras)
INTERVENTION_TYPES = (
    "Restorative conversation",
    "Parent meeting",
    "Behaviour agreement",
    "Support referral",
    "Monitoring",
    "HOD discussion",
    "Literacy remedial support",
    "Numeracy booster programme",
    "EQ / emotional regulation coaching",
    "Learning support referral",
    "Attendance support plan",
    "Classroom adjustment plan",
    "Safety / anti-bullying plan",
    "SMT formal review",
)


def _latest_by_domain(observations: list[LearnerObservation]) -> dict[str, LearnerObservation]:
    latest: dict[str, LearnerObservation] = {}
    for o in sorted(observations, key=lambda x: x.observed_at):
        latest[o.domain] = o
    return latest


def _priority_rank(p: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(p, 9)


def build_recommendations(
    *,
    learner: m.Learner,
    observations: list[LearnerObservation],
    incidents: list[m.Incident],
    offences: dict[int, m.Offence],
    interventions: list[m.Intervention],
    window_days: int = 90,
) -> list[dict]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)
    windowed = [i for i in incidents if (i.created_at.replace(tzinfo=timezone.utc) if i.created_at.tzinfo is None else i.created_at) >= since]
    latest = _latest_by_domain(observations)
    factor_counts = Counter(o.contributing_factor for o in observations[-12:] if o.contributing_factor)
    pending_types = {iv.type for iv in interventions if iv.outcome in ("pending", "follow_up")}
    recent_types = {iv.type for iv in interventions[:8]}
    similar = Counter()
    max_sev = 0
    categories = Counter()
    for i in windowed:
        o = offences.get(i.offence_id)
        if not o:
            continue
        max_sev = max(max_sev, o.severity or 0)
        categories[o.category] += 1
        similar[o.similarity_group or o.code] += 1
    top_similar = similar.most_common(1)
    latest_incident_id = windowed[0].id if windowed else (incidents[0].id if incidents else None)

    recs: list[dict] = []

    def add(code: str, priority: str, intervention_type: str, title: str, rationale: str,
            signals: list[str], owner_hint: str, urgency_days: int, factor_focus: str = "unknown"):
        if intervention_type in pending_types:
            return  # already in flight
        recs.append({
            "code": code,
            "priority": priority,
            "intervention_type": intervention_type,
            "title": title,
            "rationale": rationale,
            "signals": signals,
            "owner_hint": owner_hint,
            "urgency_days": urgency_days,
            "factor_focus": factor_focus,
            "suggested_incident_id": latest_incident_id,
        })

    # --- Learning domains ---
    reading = latest.get("reading")
    if reading and reading.level in CONCERN_LEVELS:
        add("lit_support", "high" if reading.level == "concern" else "medium",
            "Literacy remedial support",
            "Reading / literacy intervention",
            f"Latest reading note ({reading.level}): {reading.title}. "
            "Recommend structured literacy support and check school vs home reading exposure.",
            [f"reading:{reading.level}", f"factor:{reading.contributing_factor}"],
            "HOD / learning support", 7, reading.contributing_factor or "unknown")

    numeracy = latest.get("numeracy")
    if numeracy and numeracy.level in CONCERN_LEVELS:
        add("num_support", "high" if numeracy.level == "concern" else "medium",
            "Numeracy booster programme",
            "Numeracy / counting intervention",
            f"Latest numeracy note ({numeracy.level}): {numeracy.title}. "
            "Use concrete materials, untimed practice, and home number-talk partnership where relevant.",
            [f"numeracy:{numeracy.level}", f"factor:{numeracy.contributing_factor}"],
            "Class teacher / maths HOD", 7, numeracy.contributing_factor or "unknown")

    eq = latest.get("emotional_eq")
    if eq and eq.level in CONCERN_LEVELS:
        add("eq_coach", "high" if eq.level == "concern" else "medium",
            "EQ / emotional regulation coaching",
            "Emotional regulation (EQ) support",
            f"Latest EQ note ({eq.level}): {eq.title}. "
            "Coach naming feelings, calm-down routines; explore classroom relationships and home stress.",
            [f"emotional_eq:{eq.level}", f"factor:{eq.contributing_factor}"],
            "Counsellor / SMT pastoral", 5, eq.contributing_factor or "unknown")

    cog = latest.get("cognitive_assessment")
    if cog and (cog.level in CONCERN_LEVELS or (cog.score is not None and cog.score < 90)):
        score_bit = f" Score on file: {cog.score}." if cog.score is not None else ""
        add("ls_referral", "high",
            "Learning support referral",
            "Learning support / cognitive follow-up",
            f"Formal cognitive note ({cog.level}): {cog.title}.{score_bit} "
            "Refer to learning support for qualified follow-up — school staff must not invent or reinterpret IQ.",
            [f"cognitive_assessment:{cog.level}"] + ([f"score:{cog.score}"] if cog.score is not None else []),
            "Learning support / educational psychologist pathway", 10, "school")

    attendance = latest.get("attendance")
    if attendance and attendance.level in CONCERN_LEVELS:
        add("attendance", "medium",
            "Attendance support plan",
            "Attendance / engagement plan",
            f"Attendance concern: {attendance.title}. Combine school check-ins with guardian partnership.",
            [f"attendance:{attendance.level}"], "Class teacher / admin", 7,
            attendance.contributing_factor or "both")

    # --- Context factors ---
    if factor_counts.get("home", 0) >= 2:
        add("parent_partner", "high",
            "Parent meeting",
            "Parent partnership meeting (home factors)",
            f"{factor_counts['home']} recent notes cite home context. "
            "Coordinate support without blaming the family; agree routines and follow-up.",
            [f"home_factors:{factor_counts['home']}"], "HOD / class teacher", 5, "home")

    if factor_counts.get("school", 0) >= 2 and not any(r["code"] == "lit_support" for r in recs):
        add("class_adjust", "medium",
            "Classroom adjustment plan",
            "Classroom / school-context adjustment",
            f"{factor_counts['school']} recent notes cite school factors (instruction, peers, environment). "
            "Adjust seating, task design, or adult support before escalating sanctions.",
            [f"school_factors:{factor_counts['school']}"], "Class teacher / HOD", 7, "school")

    # Combined: literacy struggle + behaviour → shame/avoidance pathway
    if reading and reading.level in CONCERN_LEVELS and len(windowed) >= 2:
        add("lit_behaviour", "high",
            "Restorative conversation",
            "Link literacy struggle to behaviour (restorative + support)",
            "Reading concern coincides with repeated incidents — check whether avoidance/shame drives behaviour, "
            "and pair restorative talk with literacy support rather than punishment alone.",
            ["reading:concern_or_emerging", f"incidents_window:{len(windowed)}"],
            "HOD + learning support", 5, "both")

    # --- Behaviour / incidents ---
    if max_sev >= 3:
        add("serious_review", "critical",
            "SMT formal review",
            "Serious incident — formal structure review",
            f"Window includes severity {max_sev} incident(s). "
            "System recommends authorised review — never auto-sanctions.",
            [f"max_severity:{max_sev}", f"incidents_window:{len(windowed)}"],
            "SMT / principal", 2, "school")

    bullying_n = sum(v for k, v in categories.items() if "bull" in k.lower() or "aggress" in k.lower() or "fight" in k.lower())
    if bullying_n >= 1:
        add("safety_plan", "critical" if max_sev >= 3 else "high",
            "Safety / anti-bullying plan",
            "Safety / anti-bullying intervention",
            f"{bullying_n} fighting/aggression/bullying-related incident(s) in window. "
            "Put a safety plan and parent notification pathway in place.",
            [f"aggression_bullying:{bullying_n}"], "HOD / SMT", 2, "school")

    if top_similar and top_similar[0][1] >= 2:
        group, count = top_similar[0]
        add("repeat_behaviour", "high" if count >= 3 else "medium",
            "Behaviour agreement",
            "Repeat-behaviour agreement + monitoring",
            f"Similar behaviour cluster '{group}' occurred {count} times in {window_days} days. "
            "Recommend behaviour agreement, monitoring, and restorative follow-up.",
            [f"similar_group:{group}", f"count:{count}"], "HOD", 5, "school")
        if count >= 3 and "Monitoring" not in pending_types:
            add("repeat_monitor", "medium",
                "Monitoring",
                "Short-cycle behaviour monitoring",
                f"Escalate monitoring after {count} similar incidents — review weekly with evidence of change.",
                [f"similar_group:{group}", f"count:{count}"], "Class teacher", 3, "school")

    if len(windowed) >= 5 and "HOD discussion" not in recent_types:
        add("hod_volume", "high",
            "HOD discussion",
            "HOD case discussion (incident volume)",
            f"{len(windowed)} incidents in {window_days} days. Convene HOD discussion and consider a support case.",
            [f"incidents_window:{len(windowed)}"], "HOD", 3, "school")

    # Failed / stalled prior interventions
    stalled = [iv for iv in interventions if iv.outcome in ("no_improvement", "partially_improved")]
    if stalled and "Support referral" not in pending_types:
        add("escalate_support", "high",
            "Support referral",
            "Escalate after limited intervention effect",
            f"{len(stalled)} prior intervention(s) show limited improvement. "
            "Refer to broader support (learning support, counselling, or SMT) rather than repeating the same step.",
            [f"stalled_interventions:{len(stalled)}"], "SMT / support team", 7, "both")

    # Deduplicate by intervention_type keeping highest priority
    by_type: dict[str, dict] = {}
    for r in recs:
        prev = by_type.get(r["intervention_type"])
        if not prev or _priority_rank(r["priority"]) < _priority_rank(prev["priority"]):
            by_type[r["intervention_type"]] = r
    ordered = sorted(by_type.values(), key=lambda x: (_priority_rank(x["priority"]), x["urgency_days"], x["title"]))
    for i, r in enumerate(ordered, 1):
        r["rank"] = i
        r["domain_labels"] = [DOMAINS.get(s.split(":")[0], s) for s in r["signals"] if ":" in s and s.split(":")[0] in DOMAINS]
    return ordered


def _load_learner_context(s: Session, learner_id: int, ctx: dict):
    learner = s.scalar(select(m.Learner).where(m.Learner.id == learner_id, m.Learner.school_id == ctx["sid"]))
    if not learner:
        raise HTTPException(404, "Learner not found")
    if ctx["role"] == "educator" and learner.class_name not in ctx["assigned_classes"]:
        raise HTTPException(403, "Not assigned to learner")
    sid = ctx["sid"]
    observations = s.scalars(select(LearnerObservation).where(
        LearnerObservation.school_id == sid, LearnerObservation.learner_id == learner.id
    ).order_by(LearnerObservation.observed_at.asc())).all()
    offences = {o.id: o for o in s.scalars(select(m.Offence).where(m.Offence.school_id == sid)).all()}
    incidents = s.scalars(select(m.Incident).where(
        m.Incident.school_id == sid, m.Incident.learner_id == learner.id, m.Incident.status != "withdrawn"
    ).order_by(m.Incident.created_at.desc())).all()
    incident_ids = [i.id for i in incidents]
    interventions = []
    if incident_ids:
        interventions = s.scalars(select(m.Intervention).where(
            m.Intervention.school_id == sid, m.Intervention.incident_id.in_(incident_ids)
        ).order_by(m.Intervention.id.desc())).all()
    settings = m.setting_map(s, sid)
    window_days = m.setting_int(settings, "repeat_window_days", 90)
    return learner, observations, incidents, offences, interventions, window_days


@router.get("/learners/{learner_id}/intervention-recommendations")
def learner_recommendations(learner_id: int, s: Session = Depends(m.db), ctx=Depends(m.current)):
    if ctx["role"] not in MANAGERS and ctx["role"] != "educator":
        raise HTTPException(403, "Not authorised")
    learner, observations, incidents, offences, interventions, window_days = _load_learner_context(s, learner_id, ctx)
    recs = build_recommendations(
        learner=learner, observations=observations, incidents=incidents,
        offences=offences, interventions=interventions, window_days=window_days,
    )
    return {
        "learner_id": learner.id,
        "name": learner.first_name + " " + learner.surname,
        "grade": learner.grade,
        "window_days": window_days,
        "notice": "Recommendations are advisory detection rules from recorded behaviour, EQ, formal cognitive notes and incidents. "
                  "Staff decide. The system never issues sanctions or invents IQ/EQ scores.",
        "counts": {
            "total": len(recs),
            "critical": sum(1 for r in recs if r["priority"] == "critical"),
            "high": sum(1 for r in recs if r["priority"] == "high"),
        },
        "recommendations": recs,
        "intervention_types": list(INTERVENTION_TYPES),
    }


@router.get("/analytics/intervention-recommendations")
def school_recommendations(limit: int = 40, s: Session = Depends(m.db), ctx=Depends(m.require(*MANAGERS))):
    """School-wide board: learners with the strongest automatic intervention suggestions."""
    sid = ctx["sid"]
    settings = m.setting_map(s, sid)
    window_days = m.setting_int(settings, "repeat_window_days", 90)
    learners = s.scalars(select(m.Learner).where(m.Learner.school_id == sid, m.Learner.active == True)).all()
    offences = {o.id: o for o in s.scalars(select(m.Offence).where(m.Offence.school_id == sid)).all()}
    all_obs = s.scalars(select(LearnerObservation).where(LearnerObservation.school_id == sid)).all()
    obs_by = {}
    for o in all_obs:
        obs_by.setdefault(o.learner_id, []).append(o)
    all_inc = s.scalars(select(m.Incident).where(m.Incident.school_id == sid, m.Incident.status != "withdrawn")).all()
    inc_by = {}
    for i in all_inc:
        inc_by.setdefault(i.learner_id, []).append(i)
    all_iv = s.scalars(select(m.Intervention).where(m.Intervention.school_id == sid)).all()
    iv_by_incident = {}
    for iv in all_iv:
        iv_by_incident.setdefault(iv.incident_id, []).append(iv)

    board = []
    for learner in learners:
        incidents = sorted(inc_by.get(learner.id, []), key=lambda x: x.created_at, reverse=True)
        interventions = []
        for i in incidents:
            interventions.extend(iv_by_incident.get(i.id, []))
        recs = build_recommendations(
            learner=learner, observations=obs_by.get(learner.id, []),
            incidents=incidents, offences=offences, interventions=interventions, window_days=window_days,
        )
        if not recs:
            continue
        top = recs[0]
        board.append({
            "learner_id": learner.id,
            "name": learner.first_name + " " + learner.surname,
            "grade": learner.grade,
            "class_name": learner.class_name,
            "top_priority": top["priority"],
            "top_title": top["title"],
            "top_type": top["intervention_type"],
            "recommendation_count": len(recs),
            "critical": sum(1 for r in recs if r["priority"] == "critical"),
            "high": sum(1 for r in recs if r["priority"] == "high"),
        })
    board.sort(key=lambda x: (_priority_rank(x["top_priority"]), -x["critical"], -x["high"], -x["recommendation_count"], x["name"]))
    return {
        "window_days": window_days,
        "notice": "Auto-detected intervention needs across the school. Advisory only — authorised staff decide.",
        "items": board[: max(1, min(limit, 100))],
        "counts": {"learners_flagged": len(board)},
    }
