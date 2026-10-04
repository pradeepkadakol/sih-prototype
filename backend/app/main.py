"""VeriSight demo REST API. All identities and records are fictional."""

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .database import initialize_database, make_engine
from .logic import ALGORITHM, candidate_weights, distance_meters, missing_required, select_inspector
from .models import (AuditEvent, AssignmentEvent, ChecklistResponse, Evidence, Finding,
                     FollowUpAction, Inspection, InspectionCase, RemoteVerificationEvent, SessionToken, Site, User, now)
from .seed import DEFAULT_TEMPLATE
from .storage import EvidenceStore, StorageError, SupabaseEvidenceStore


load_dotenv(Path(__file__).resolve().parents[2] / ".env")
logger = logging.getLogger(__name__)


def iso(value):
    if isinstance(value, datetime):
        return as_utc(value).isoformat()
    return value.isoformat() if value else None


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone-aware columns."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class LoginBody(BaseModel):
    username: str
    password: str


class CaseBody(BaseModel):
    site_id: int
    excluded_inspector_ids: list[int] = Field(default_factory=list)


class AssignBody(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class CheckInBody(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100000)
    demo_override: bool = False


class ChecklistAnswer(BaseModel):
    item_key: str
    answer: str
    note: str = Field(default="", max_length=1000)

    @field_validator("answer")
    @classmethod
    def validate_answer(cls, value):
        if value not in {"pass", "fail", "na"}:
            raise ValueError("Answer must be pass, fail, or na")
        return value


class ChecklistBody(BaseModel):
    responses: list[ChecklistAnswer]


class FindingBody(BaseModel):
    severity: str
    category: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=5, max_length=2000)
    recommended_action: str = Field(min_length=3, max_length=1000)


class EvidenceBody(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    mime_type: str
    data_base64: str
    client_capture_time: str | None = Field(default=None, max_length=50)
    client_latitude: float | None = Field(default=None, ge=-90, le=90)
    client_longitude: float | None = Field(default=None, ge=-180, le=180)


class ReviewBody(BaseModel):
    status: str
    note: str = Field(min_length=3, max_length=1000)


class FollowUpBody(BaseModel):
    owner: str = Field(min_length=2, max_length=120)
    due_date: date
    status: str = "open"


class FollowUpStatusBody(BaseModel):
    status: str
    note: str = Field(min_length=3, max_length=500)


class RemoteBody(BaseModel):
    case_id: int
    outcome: str
    note: str = Field(min_length=3, max_length=500)


def user_json(user: User | None):
    if user is None:
        return None
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role,
            "active": user.active, "available": user.available, "qualified_high_risk": user.qualified_high_risk}


def site_json(site: Site):
    return {"id": site.id, "code": site.code, "name": site.name, "organization": site.organization,
            "region": site.region, "latitude": site.latitude, "longitude": site.longitude, "risk": site.risk}


def assignment_json(event: AssignmentEvent, db: Session):
    revealed = db.scalar(select(AuditEvent.id).where(AuditEvent.action == "assignment_seed_revealed", AuditEvent.entity_type == "assignment", AuditEvent.entity_id == event.id).limit(1)) is not None
    return {"id": event.id, "case_id": event.case_id, "event_number": event.event_number,
            "eligible": json.loads(event.eligible_json), "selected_inspector_id": event.selected_inspector_id,
            "selected_inspector": user_json(db.get(User, event.selected_inspector_id)),
            "commitment": event.commitment, "algorithm": event.algorithm, "reason": event.reason,
            "selected_at": iso(event.selected_at), "revealed": revealed, **({"seed": event.seed_hex} if revealed else {})}


def finding_json(finding: Finding, db: Session):
    inspection = db.get(Inspection, finding.inspection_id)
    return {"id": finding.id, "inspection_id": finding.inspection_id, "case_id": inspection.case_id, "severity": finding.severity,
            "category": finding.category, "description": finding.description, "recommended_action": finding.recommended_action,
            "review_status": finding.review_status, "review_note": finding.review_note,
            "reviewer": user_json(db.get(User, finding.reviewer_id)) if finding.reviewer_id else None,
            "created_at": iso(finding.created_at), "reviewed_at": iso(finding.reviewed_at)}


def evidence_json(evidence: Evidence):
    return {"id": evidence.id, "inspection_id": evidence.inspection_id, "inspector_id": evidence.inspector_id,
            "original_filename": evidence.original_filename, "mime_type": evidence.mime_type,
            "size_bytes": evidence.size_bytes, "sha256": evidence.sha256, "server_received_at": iso(evidence.server_received_at),
            "client_capture_time": evidence.client_capture_time, "client_latitude": evidence.client_latitude,
            "client_longitude": evidence.client_longitude}


def followup_json(action: FollowUpAction):
    return {"id": action.id, "finding_id": action.finding_id, "owner": action.owner, "due_date": iso(action.due_date),
            "status": action.status, "history": json.loads(action.history_json), "created_at": iso(action.created_at),
            "updated_at": iso(action.updated_at), "overdue": action.status != "closed" and action.due_date < date.today()}


def risk_flags(case: InspectionCase, site: Site, inspection: Inspection | None, db: Session):
    flags = []
    if site.risk == "high":
        flags.append("High-risk site classification")
    if case.status != "completed" and as_utc(case.created_at) < now() - timedelta(days=5):
        flags.append("Inspection remains open more than five days after creation")
    if inspection:
        if inspection.geofence_result in {"outside", "demo_override", "unavailable"}:
            flags.append("Check-in location was not verified within the geofence")
        if inspection.reported_accuracy_m and inspection.reported_accuracy_m > 100:
            flags.append("Client-reported location accuracy is worse than 100 m")
        if inspection.submitted_at and (as_utc(inspection.submitted_at) - as_utc(inspection.checkin_at)).total_seconds() < 300:
            flags.append("Inspection submitted within five minutes of check-in")
        fails = db.scalars(select(ChecklistResponse).where(ChecklistResponse.inspection_id == inspection.id, ChecklistResponse.answer == "fail")).all()
        if fails and not db.scalar(select(Evidence.id).where(Evidence.inspection_id == inspection.id).limit(1)):
            flags.append("Failed checklist response has no attached evidence")
    severe_count = db.scalar(select(func.count(Finding.id)).join(Inspection, Finding.inspection_id == Inspection.id).join(InspectionCase, Inspection.case_id == InspectionCase.id).where(InspectionCase.site_id == site.id, Finding.severity == "high")) or 0
    if severe_count >= 2:
        flags.append("Repeated high-severity findings at this site")
    return flags


def case_json(case: InspectionCase, db: Session, detailed: bool = False):
    site = db.get(Site, case.site_id)
    inspection = db.scalar(select(Inspection).where(Inspection.case_id == case.id))
    result = {"id": case.id, "code": case.code, "status": case.status, "site": site_json(site),
              "assigned_inspector": user_json(db.get(User, case.assigned_inspector_id)) if case.assigned_inspector_id else None,
              "created_at": iso(case.created_at), "assigned_at": iso(case.assigned_at), "started_at": iso(case.started_at),
              "completed_at": iso(case.completed_at), "seeded": case.seeded, "risk_flags": risk_flags(case, site, inspection, db)}
    if not detailed:
        return result
    responses = db.scalars(select(ChecklistResponse).where(ChecklistResponse.inspection_id == inspection.id)).all() if inspection else []
    findings = db.scalars(select(Finding).where(Finding.inspection_id == inspection.id).order_by(Finding.created_at.desc())).all() if inspection else []
    evidence = db.scalars(select(Evidence).where(Evidence.inspection_id == inspection.id).order_by(Evidence.server_received_at.desc())).all() if inspection else []
    assignments = db.scalars(select(AssignmentEvent).where(AssignmentEvent.case_id == case.id).order_by(AssignmentEvent.event_number)).all()
    remotes = db.scalars(select(RemoteVerificationEvent).where(RemoteVerificationEvent.case_id == case.id).order_by(RemoteVerificationEvent.created_at.desc())).all()
    result.update({"template": json.loads(case.template_json), "excluded_inspector_ids": json.loads(case.excluded_ids_json),
                   "inspection": ({"id": inspection.id, "checkin_at": iso(inspection.checkin_at), "client_latitude": inspection.client_latitude,
                                   "client_longitude": inspection.client_longitude, "reported_accuracy_m": inspection.reported_accuracy_m,
                                   "distance_m": inspection.distance_m, "geofence_result": inspection.geofence_result,
                                   "submitted_at": iso(inspection.submitted_at)} if inspection else None),
                   "responses": [{"item_key": row.item_key, "answer": row.answer, "note": row.note, "updated_at": iso(row.updated_at)} for row in responses],
                   "findings": [finding_json(row, db) for row in findings], "evidence": [evidence_json(row) for row in evidence],
                   "follow_ups": [followup_json(row) for finding in findings for row in db.scalars(select(FollowUpAction).where(FollowUpAction.finding_id == finding.id)).all()],
                   "assignment_history": [assignment_json(row, db) for row in assignments],
                   "remote_verifications": [{"id": row.id, "outcome": row.outcome, "note": row.note, "created_at": iso(row.created_at)} for row in remotes]})
    return result


def audit(db: Session, actor_id: int | None, action: str, entity_type: str, entity_id: int, details: str = ""):
    db.add(AuditEvent(actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id, details=details[:500]))


def create_app(database_url: str | None = None, evidence_store: EvidenceStore | None = None,
               initialize: bool = False) -> FastAPI:
    if database_url is None:
        database_url = os.getenv("DATABASE_URL", "")
        if not database_url.startswith(("postgresql://", "postgres://", "postgresql+psycopg://")):
            raise RuntimeError("Set DATABASE_URL to your Supabase PostgreSQL URL in the root .env file")
    if evidence_store is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "verisight-evidence")
        if not url or not key:
            raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the root .env file")
        evidence_store = SupabaseEvidenceStore(url, key, bucket)
    engine = make_engine(database_url)
    if initialize:
        initialize_database(engine)
    SessionLocal = sessionmaker(engine, expire_on_commit=False)

    app = FastAPI(title="VeriSight Demo API", version="0.1.0", description="Fictional SIH26095 prototype; not production-ready.")
    app.add_middleware(CORSMiddleware, allow_origins=os.getenv("FRONTEND_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(","), allow_credentials=True, allow_methods=["GET", "POST", "PUT"], allow_headers=["Authorization", "Content-Type"])

    def get_db():
        with SessionLocal() as db:
            yield db

    def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Demo login required")
        token_hash = hashlib.sha256(authorization[7:].encode()).hexdigest()
        row = db.scalar(select(SessionToken).where(SessionToken.token_hash == token_hash))
        if not row or as_utc(row.created_at) < now() - timedelta(hours=12):
            raise HTTPException(401, "Session expired; log in again")
        user = db.get(User, row.user_id)
        if not user or not user.active:
            raise HTTPException(401, "Demo account unavailable")
        return user

    def reviewer(user: User = Depends(current_user)):
        if user.role != "reviewer":
            raise HTTPException(403, "Reviewer role required")
        return user

    def load_case(case_id: int, db: Session, user: User):
        case = db.get(InspectionCase, case_id)
        if not case:
            raise HTTPException(404, "Inspection case not found")
        if user.role == "inspector" and case.assigned_inspector_id != user.id:
            raise HTTPException(403, "This case is not assigned to you")
        return case

    def working_inspection(case_id: int, db: Session, user: User):
        case = load_case(case_id, db, user)
        if user.role != "inspector":
            raise HTTPException(403, "Inspector role required")
        inspection = db.scalar(select(Inspection).where(Inspection.case_id == case.id))
        if not inspection or case.status != "in_progress":
            raise HTTPException(409, "Start the inspection before editing")
        if inspection.inspector_id != user.id:
            raise HTTPException(403, "This inspection belongs to another inspector")
        return case, inspection

    @app.post("/api/login")
    def login(body: LoginBody, db: Session = Depends(get_db)):
        user = db.scalar(select(User).where(User.username == body.username))
        if not user or not user.active:
            raise HTTPException(401, "Invalid demo credentials")
        try:
            salt, expected = user.password_hash.split("$", 1)
            calculated = hashlib.pbkdf2_hmac("sha256", body.password.encode(), bytes.fromhex(salt), 150_000).hex()
        except ValueError:
            raise HTTPException(401, "Invalid demo credentials")
        if not hmac.compare_digest(calculated, expected):
            raise HTTPException(401, "Invalid demo credentials")
        token = secrets.token_urlsafe(32)
        db.add(SessionToken(user_id=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest()))
        audit(db, user.id, "login", "user", user.id)
        db.commit()
        return {"token": token, "user": user_json(user), "demo_mode": True}

    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        return user_json(user)

    @app.get("/api/users")
    def users(db: Session = Depends(get_db), _user: User = Depends(reviewer)):
        return [user_json(row) for row in db.scalars(select(User).order_by(User.id)).all()]

    @app.get("/api/sites")
    def sites(db: Session = Depends(get_db), _user: User = Depends(current_user)):
        return [site_json(row) for row in db.scalars(select(Site).order_by(Site.id)).all()]

    @app.get("/api/inspections")
    def inspections(region: str | None = None, site: str | None = None, risk: str | None = None,
                    status: str | None = None, created_after: date | None = None,
                    db: Session = Depends(get_db), user: User = Depends(current_user)):
        query = select(InspectionCase).join(Site).order_by(InspectionCase.created_at.desc())
        if user.role == "inspector":
            query = query.where(InspectionCase.assigned_inspector_id == user.id)
        if region:
            query = query.where(Site.region == region)
        if site:
            query = query.where((Site.name.ilike(f"%{site}%")) | (Site.organization.ilike(f"%{site}%")))
        if risk:
            query = query.where(Site.risk == risk)
        if status:
            query = query.where(InspectionCase.status == status)
        if created_after:
            query = query.where(InspectionCase.created_at >= datetime.combine(created_after, datetime.min.time(), timezone.utc))
        return [case_json(case, db) for case in db.scalars(query).all()]

    @app.post("/api/inspections", status_code=201)
    def create_case(body: CaseBody, db: Session = Depends(get_db), user: User = Depends(reviewer)):
        site = db.get(Site, body.site_id)
        if not site:
            raise HTTPException(422, "Select a valid site")
        excluded = sorted(set(body.excluded_inspector_ids))
        if any(not db.get(User, uid) or db.get(User, uid).role != "inspector" for uid in excluded):
            raise HTTPException(422, "Excluded inspector ID is invalid")
        case = InspectionCase(code=f"VI-{datetime.now(timezone.utc):%y%m%d}-{secrets.token_hex(3).upper()}", site_id=site.id,
                              status="pending", excluded_ids_json=json.dumps(excluded), template_json=json.dumps(DEFAULT_TEMPLATE), seeded=False)
        db.add(case)
        db.flush()
        audit(db, user.id, "case_created", "case", case.id, site.name)
        db.commit()
        return case_json(case, db, True)

    @app.get("/api/inspections/{case_id}")
    def inspection_detail(case_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
        return case_json(load_case(case_id, db, user), db, True)

    @app.post("/api/inspections/{case_id}/assign")
    def assign(case_id: int, body: AssignBody, db: Session = Depends(get_db), user: User = Depends(reviewer)):
        case = load_case(case_id, db, user)
        if case.status not in {"pending", "assigned"}:
            raise HTTPException(409, "Started or completed inspections cannot be reassigned")
        previous = db.scalars(select(AssignmentEvent).where(AssignmentEvent.case_id == case.id).order_by(AssignmentEvent.event_number)).all()
        if previous and not (body.reason or "").strip():
            raise HTTPException(409, "Reassignment requires a reason")
        site = db.get(Site, case.site_id)
        inspector_rows = db.scalars(select(User).where(User.role == "inspector")).all()
        candidates = candidate_weights([user_json(row) for row in inspector_rows], site.risk, json.loads(case.excluded_ids_json))
        if not candidates:
            raise HTTPException(409, "No eligible inspectors are available")
        seed = secrets.token_bytes(32)
        number = len(previous) + 1
        selected = select_inspector(seed, case.id, candidates, number)
        assignment = AssignmentEvent(case_id=case.id, event_number=number,
                                     eligible_json=json.dumps(candidates, separators=(",", ":")),
                                     selected_inspector_id=selected, seed_hex=seed.hex(), commitment=hashlib.sha256(seed).hexdigest(),
                                     algorithm=ALGORITHM, reason=(body.reason or "").strip() or None)
        db.add(assignment)
        db.flush()
        case.assigned_inspector_id = selected
        case.assigned_at = assignment.selected_at
        case.status = "assigned"
        audit(db, user.id, "case_assigned" if number == 1 else "case_reassigned", "case", case.id, f"Event {number}; inspector {selected}")
        db.commit()
        return assignment_json(assignment, db)

    @app.get("/api/inspections/{case_id}/assignment-history")
    def assignment_history(case_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
        load_case(case_id, db, user)
        return [assignment_json(row, db) for row in db.scalars(select(AssignmentEvent).where(AssignmentEvent.case_id == case_id).order_by(AssignmentEvent.event_number)).all()]

    @app.post("/api/assignments/{assignment_id}/reveal-seed")
    def reveal_seed(assignment_id: int, db: Session = Depends(get_db), user: User = Depends(reviewer)):
        assignment = db.get(AssignmentEvent, assignment_id)
        if not assignment:
            raise HTTPException(404, "Assignment event not found")
        audit(db, user.id, "assignment_seed_revealed", "assignment", assignment.id, "Demo verification requested")
        db.commit()
        return assignment_json(assignment, db)

    @app.post("/api/inspections/{case_id}/check-in")
    def check_in(case_id: int, body: CheckInBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
        case = load_case(case_id, db, user)
        if user.role != "inspector":
            raise HTTPException(403, "Inspector role required")
        if case.status != "assigned":
            raise HTTPException(409, "Case must be assigned and not yet started")
        if (body.latitude is None) != (body.longitude is None):
            raise HTTPException(422, "Latitude and longitude must be reported together")
        site = db.get(Site, case.site_id)
        distance = distance_meters(body.latitude, body.longitude, site.latitude, site.longitude) if body.latitude is not None else None
        radius = float(os.getenv("GEOFENCE_RADIUS_METERS", "250"))
        within = distance is not None and distance <= radius
        if not within and not body.demo_override:
            raise HTTPException(422, "Location unavailable or outside geofence. Seeded cases may use the labelled demo override.")
        if body.demo_override and not case.seeded:
            raise HTTPException(403, "Demo override is available only on seeded cases")
        result = "demo_override" if body.demo_override else "within"
        inspection = Inspection(case_id=case.id, inspector_id=user.id, client_latitude=body.latitude,
                                client_longitude=body.longitude, reported_accuracy_m=body.accuracy_m,
                                distance_m=distance, geofence_result=result)
        db.add(inspection)
        db.flush()
        case.status = "in_progress"
        case.started_at = inspection.checkin_at
        audit(db, user.id, "inspection_checked_in", "inspection", inspection.id, result)
        db.commit()
        return case_json(case, db, True)

    @app.put("/api/inspections/{case_id}/checklist")
    def save_checklist(case_id: int, body: ChecklistBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
        case, inspection = working_inspection(case_id, db, user)
        keys = {item["key"] for item in json.loads(case.template_json)}
        if len({row.item_key for row in body.responses}) != len(body.responses) or any(row.item_key not in keys for row in body.responses):
            raise HTTPException(422, "Checklist has unknown or duplicate item keys")
        for item in body.responses:
            row = db.scalar(select(ChecklistResponse).where(ChecklistResponse.inspection_id == inspection.id, ChecklistResponse.item_key == item.item_key))
            if not row:
                row = ChecklistResponse(inspection_id=inspection.id, item_key=item.item_key, answer=item.answer, note=item.note)
                db.add(row)
            else:
                row.answer, row.note, row.updated_at = item.answer, item.note, now()
        audit(db, user.id, "checklist_saved", "inspection", inspection.id, f"{len(body.responses)} responses")
        db.commit()
        return case_json(case, db, True)

    @app.post("/api/inspections/{case_id}/findings", status_code=201)
    def add_finding(case_id: int, body: FindingBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
        _, inspection = working_inspection(case_id, db, user)
        if body.severity not in {"low", "medium", "high"}:
            raise HTTPException(422, "Severity must be low, medium, or high")
        finding = Finding(inspection_id=inspection.id, severity=body.severity, category=body.category.strip(),
                          description=body.description.strip(), recommended_action=body.recommended_action.strip())
        db.add(finding)
        db.flush()
        audit(db, user.id, "finding_created", "finding", finding.id, body.severity)
        db.commit()
        return finding_json(finding, db)

    @app.post("/api/inspections/{case_id}/evidence", status_code=201)
    def add_evidence(case_id: int, body: EvidenceBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
        _, inspection = working_inspection(case_id, db, user)
        allowed = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
        if body.mime_type not in allowed:
            raise HTTPException(422, "Only PNG, JPEG, and WebP images are supported")
        if len(body.data_base64) > 8_000_000:
            raise HTTPException(413, "Evidence exceeds 5 MB")
        try:
            content = base64.b64decode(body.data_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "Invalid base64 evidence data")
        if not content or len(content) > 5_000_000:
            raise HTTPException(413, "Evidence must be between 1 byte and 5 MB")
        signatures = {"image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
                      "image/jpeg": content.startswith(b"\xff\xd8\xff"),
                      "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP"}
        if not signatures[body.mime_type]:
            raise HTTPException(422, "File bytes do not match the declared image type")
        filename = f"inspections/{inspection.id}/{uuid.uuid4().hex}{allowed[body.mime_type]}"
        try:
            evidence_store.upload(filename, content, body.mime_type)
        except StorageError:
            logger.exception("Evidence upload failed")
            raise HTTPException(503, "Evidence storage is unavailable; retry the upload")
        evidence = Evidence(inspection_id=inspection.id, inspector_id=user.id,
                            original_filename=Path(body.filename.replace("\\", "/")).name,
                            storage_filename=filename, mime_type=body.mime_type, size_bytes=len(content),
                            sha256=hashlib.sha256(content).hexdigest(), client_capture_time=body.client_capture_time,
                            client_latitude=body.client_latitude, client_longitude=body.client_longitude)
        try:
            db.add(evidence)
            db.flush()
            audit(db, user.id, "evidence_added", "evidence", evidence.id, evidence.sha256)
            db.commit()
        except Exception:
            db.rollback()
            try:
                evidence_store.delete(filename)
            except StorageError:
                logger.exception("Could not remove uploaded evidence after database failure")
            raise
        return evidence_json(evidence)

    @app.post("/api/inspections/{case_id}/submit")
    def submit(case_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
        case, inspection = working_inspection(case_id, db, user)
        responses = db.scalars(select(ChecklistResponse).where(ChecklistResponse.inspection_id == inspection.id)).all()
        missing = missing_required(json.loads(case.template_json), {row.item_key: row.answer for row in responses})
        if missing:
            raise HTTPException(409, f"Required checklist items unanswered: {', '.join(missing)}")
        inspection.submitted_at = now()
        case.completed_at = inspection.submitted_at
        case.status = "completed"
        audit(db, user.id, "inspection_submitted", "inspection", inspection.id, case.code)
        db.commit()
        return case_json(case, db, True)

    @app.post("/api/findings/{finding_id}/review")
    def review_finding(finding_id: int, body: ReviewBody, db: Session = Depends(get_db), user: User = Depends(reviewer)):
        finding = db.get(Finding, finding_id)
        if not finding:
            raise HTTPException(404, "Finding not found")
        if body.status not in {"accepted", "needs_clarification", "dismissed"}:
            raise HTTPException(422, "Invalid review status")
        inspection = db.get(Inspection, finding.inspection_id)
        if inspection.inspector_id == user.id:
            raise HTTPException(403, "Inspectors cannot review their own findings")
        finding.review_status, finding.review_note, finding.reviewer_id, finding.reviewed_at = body.status, body.note.strip(), user.id, now()
        audit(db, user.id, "finding_reviewed", "finding", finding.id, body.status)
        db.commit()
        return finding_json(finding, db)

    @app.post("/api/findings/{finding_id}/follow-ups", status_code=201)
    def create_followup(finding_id: int, body: FollowUpBody, db: Session = Depends(get_db), user: User = Depends(reviewer)):
        finding = db.get(Finding, finding_id)
        if not finding:
            raise HTTPException(404, "Finding not found")
        if body.status not in {"open", "in_progress", "closed"}:
            raise HTTPException(422, "Invalid follow-up status")
        action = FollowUpAction(finding_id=finding.id, owner=body.owner.strip(), due_date=body.due_date, status=body.status,
                                history_json=json.dumps([{"status": body.status, "at": iso(now()), "actor": user.display_name, "note": "Created"}]))
        db.add(action)
        db.flush()
        audit(db, user.id, "followup_created", "follow_up", action.id, action.owner)
        db.commit()
        return followup_json(action)

    @app.put("/api/follow-ups/{followup_id}")
    def update_followup(followup_id: int, body: FollowUpStatusBody, db: Session = Depends(get_db), user: User = Depends(reviewer)):
        action = db.get(FollowUpAction, followup_id)
        if not action:
            raise HTTPException(404, "Follow-up not found")
        if body.status not in {"open", "in_progress", "closed"}:
            raise HTTPException(422, "Invalid follow-up status")
        history = json.loads(action.history_json)
        history.append({"status": body.status, "at": iso(now()), "actor": user.display_name, "note": body.note.strip()})
        action.status, action.history_json, action.updated_at = body.status, json.dumps(history), now()
        audit(db, user.id, "followup_updated", "follow_up", action.id, body.status)
        db.commit()
        return followup_json(action)

    @app.post("/api/remote-verification/simulate", status_code=201)
    def remote_verification(body: RemoteBody, db: Session = Depends(get_db), user: User = Depends(reviewer)):
        load_case(body.case_id, db, user)
        if body.outcome not in {"observed", "needs_visit", "inconclusive"}:
            raise HTTPException(422, "Invalid simulated outcome")
        row = RemoteVerificationEvent(case_id=body.case_id, reviewer_id=user.id, outcome=body.outcome, note=body.note.strip())
        db.add(row)
        db.flush()
        audit(db, user.id, "remote_verification_simulated", "case", body.case_id, body.outcome)
        db.commit()
        return {"id": row.id, "case_id": row.case_id, "outcome": row.outcome, "note": row.note, "created_at": iso(row.created_at), "simulated": True}

    @app.get("/api/dashboard/summary")
    def dashboard(db: Session = Depends(get_db), _user: User = Depends(reviewer)):
        cases = db.scalars(select(InspectionCase).order_by(InspectionCase.created_at.desc())).all()
        sites = db.scalars(select(Site).order_by(Site.id)).all()
        actions = db.scalars(select(FollowUpAction).order_by(FollowUpAction.created_at.desc())).all()
        findings = db.scalars(select(Finding).order_by(Finding.created_at.desc())).all()
        activity = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(12)).all()
        completed_sites = {case.site_id for case in cases if case.status == "completed"}
        return {"total": len(cases), "pending": sum(case.status == "pending" for case in cases),
                "in_progress": sum(case.status == "in_progress" for case in cases),
                "assigned": sum(case.status == "assigned" for case in cases),
                "completed": sum(case.status == "completed" for case in cases),
                "overdue_followups": sum(row.status != "closed" and row.due_date < date.today() for row in actions),
                "coverage": {"inspected_sites": len(completed_sites), "total_sites": len(sites), "percent": round(100 * len(completed_sites) / len(sites)) if sites else 0, "region": "Fictional Nila District"},
                "sites": [site_json(site) | {"status": next((case.status for case in cases if case.site_id == site.id), "none")} for site in sites],
                "recent_findings": [finding_json(row, db) for row in findings],
                "follow_ups": [followup_json(row) for row in actions],
                "activity": [{"id": row.id, "actor": db.get(User, row.actor_id).display_name if row.actor_id else "Demo system", "action": row.action,
                              "entity_type": row.entity_type, "entity_id": row.entity_id, "details": row.details, "created_at": iso(row.created_at)} for row in activity]}

    return app


# Uvicorn loads this callable with --factory after environment configuration.
app = create_app
