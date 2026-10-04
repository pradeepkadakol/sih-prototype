import hashlib
import json
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .logic import ALGORITHM, candidate_weights, select_inspector
from .models import AuditEvent, AssignmentEvent, ChecklistResponse, Finding, FollowUpAction, Inspection, InspectionCase, Site, User, now


DEFAULT_TEMPLATE = [
    {"key": "entry", "label": "Site access and entry log verified", "required": True},
    {"key": "safety", "label": "Safety barriers and signage inspected", "required": True},
    {"key": "equipment", "label": "Equipment condition recorded", "required": True},
    {"key": "records", "label": "Operating records checked", "required": False},
]


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 150_000).hex()
    return f"{salt}${digest}"


def seed_database(db: Session) -> None:
    if db.scalar(select(User.id).limit(1)) is not None:
        return
    users = [
        User(username="reviewer", display_name="Demo Review Officer", role="reviewer", password_hash=hash_password("demo1234")),
        User(username="inspector.arya", display_name="Arya Sen (fictional)", role="inspector", password_hash=hash_password("demo1234"), qualified_high_risk=True),
        User(username="inspector.kiran", display_name="Kiran Rao (fictional)", role="inspector", password_hash=hash_password("demo1234")),
        User(username="inspector.meera", display_name="Meera Das (fictional)", role="inspector", password_hash=hash_password("demo1234"), qualified_high_risk=True),
        User(username="inspector.offline", display_name="Unavailable Inspector", role="inspector", password_hash=hash_password("demo1234"), available=False),
    ]
    db.add_all(users)
    sites = [
        Site(code="NL-101", name="North Canal Pump House", organization="Nila Water Board", region="Nila North", latitude=13.0194, longitude=77.5946, risk="high"),
        Site(code="NL-102", name="East Grid Substation", organization="Nila Energy Office", region="Nila East", latitude=12.9951, longitude=77.6532, risk="high"),
        Site(code="NL-103", name="Lakeside Treatment Unit", organization="Nila Water Board", region="Nila East", latitude=12.9611, longitude=77.6417, risk="medium"),
        Site(code="NL-104", name="Civic Stores Depot", organization="Nila Civic Works", region="Nila Central", latitude=12.9751, longitude=77.6064, risk="low"),
        Site(code="NL-105", name="West Transfer Station", organization="Nila Civic Works", region="Nila West", latitude=12.9707, longitude=77.5341, risk="medium"),
        Site(code="NL-106", name="Hill Reservoir Annex", organization="Nila Water Board", region="Nila North", latitude=13.0542, longitude=77.5686, risk="high"),
    ]
    db.add_all(sites)
    db.flush()
    date = now()
    cases = [
        InspectionCase(code="VI-26095-001", site_id=sites[0].id, status="pending", seeded=True, template_json=json.dumps(DEFAULT_TEMPLATE), created_at=date - timedelta(days=2)),
        InspectionCase(code="VI-26095-002", site_id=sites[1].id, status="assigned", seeded=True, template_json=json.dumps(DEFAULT_TEMPLATE), created_at=date - timedelta(days=3)),
        InspectionCase(code="VI-26095-003", site_id=sites[2].id, status="in_progress", seeded=True, template_json=json.dumps(DEFAULT_TEMPLATE), created_at=date - timedelta(days=4)),
        InspectionCase(code="VI-26095-004", site_id=sites[3].id, status="completed", seeded=True, template_json=json.dumps(DEFAULT_TEMPLATE), created_at=date - timedelta(days=7)),
        InspectionCase(code="VI-26095-005", site_id=sites[4].id, status="pending", seeded=True, template_json=json.dumps(DEFAULT_TEMPLATE), created_at=date - timedelta(days=1)),
        InspectionCase(code="VI-26095-006", site_id=sites[5].id, status="completed", seeded=True, template_json=json.dumps(DEFAULT_TEMPLATE), created_at=date - timedelta(days=9)),
    ]
    db.add_all(cases)
    db.flush()
    inspector_rows = [{"id": u.id, "active": u.active, "available": u.available, "qualified_high_risk": u.qualified_high_risk} for u in users if u.role == "inspector"]
    for case in cases[1:4] + cases[5:]:
        site = next(site for site in sites if site.id == case.site_id)
        eligible = candidate_weights(inspector_rows, site.risk, [])
        seed = secrets.token_bytes(32)
        selected = select_inspector(seed, case.id, eligible, 1)
        case.assigned_inspector_id = selected
        case.assigned_at = case.created_at + timedelta(hours=5)
        db.add(AssignmentEvent(case_id=case.id, event_number=1, eligible_json=json.dumps(eligible, separators=(",", ":")), selected_inspector_id=selected, seed_hex=seed.hex(), commitment=hashlib.sha256(seed).hexdigest(), algorithm=ALGORITHM, reason="Seeded demo assignment", selected_at=case.assigned_at))
    for case in (cases[2], cases[3], cases[5]):
        case.started_at = case.assigned_at + timedelta(days=1)
        inspection = Inspection(case_id=case.id, inspector_id=case.assigned_inspector_id, checkin_at=case.started_at, geofence_result="demo_override")
        db.add(inspection)
        db.flush()
        if case.status == "completed":
            case.completed_at = case.started_at + timedelta(hours=2)
            inspection.submitted_at = case.completed_at
            db.add_all([ChecklistResponse(inspection_id=inspection.id, item_key=item["key"], answer="pass", note="Seeded observation") for item in DEFAULT_TEMPLATE if item["required"]])
            finding = Finding(inspection_id=inspection.id, category="Safety", severity="high" if case == cases[5] else "medium", description="Fictional maintenance issue noted during demo inspection.", recommended_action="Schedule maintenance review.", review_status="accepted", review_note="Accepted for demo follow-up", reviewer_id=users[0].id, reviewed_at=case.completed_at)
            db.add(finding)
            db.flush()
            due = (date - timedelta(days=2) if case == cases[5] else date + timedelta(days=5)).date()
            db.add(FollowUpAction(finding_id=finding.id, owner="Nila Maintenance Cell", due_date=due, status="open", history_json=json.dumps([{"status": "open", "at": case.completed_at.isoformat(), "actor": "Demo Review Officer"}])))
    db.add(AuditEvent(actor_id=None, action="demo_seeded", entity_type="system", entity_id=0, details="Fictional Nila District records initialized"))
    db.commit()
