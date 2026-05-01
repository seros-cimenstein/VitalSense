"""HTTP API routes for VitalSense."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_engine, get_repo, get_sos
from app.core import AnomalyDetectionEngine, BreachReason
from app.db import Repository
from app.models import (
    Doctor,
    Event,
    EventType,
    FamilyMember,
    HealthRecord,
    HealthSnapshot,
    Patient,
    PersonalizedThresholds,
)
from app.services import SOSService


router = APIRouter(prefix="/api", tags=["vitalsense"])


# ---------------------------------------------------------------------------
# Request bodies (separate from domain models so the API surface is explicit)
# ---------------------------------------------------------------------------

class CreatePatientRequest(BaseModel):
    name: str
    contact_number: str
    location: Optional[str] = None
    age: int
    height_cm: float
    weight_kg: float
    doctor_id: Optional[str] = None


class CreateDoctorRequest(BaseModel):
    name: str
    contact_number: str
    location: Optional[str] = None
    specialty: str
    on_call_status: bool = True


class CreateFamilyRequest(BaseModel):
    name: str
    contact_number: str
    relationship: str
    patient_id: str
    location: Optional[str] = None


class TelemetryRequest(BaseModel):
    heart_rate: int = Field(..., ge=0, le=300)
    body_temperature: float = Field(..., ge=20.0, le=45.0)
    daily_steps: int = Field(0, ge=0)


class PatientStatus(BaseModel):
    patient_id: str
    risk_level: str
    risk_score: int
    summary: str
    latest_record: Optional[HealthRecord] = None
    verification_pending: bool
    verification_deadline: Optional[datetime] = None
    seconds_remaining: Optional[int] = None
    recent_breach_count: int
    sos_active: bool
    call_attempted: bool
    family_notifications_sent: int
    doctor_notifications_sent: int


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@router.post("/patients", response_model=Patient, status_code=status.HTTP_201_CREATED)
async def create_patient(body: CreatePatientRequest, repo: Repository = Depends(get_repo)) -> Patient:
    patient = Patient(
        name=body.name,
        contact_number=body.contact_number,
        location=body.location,
        age=body.age,
        height_cm=body.height_cm,
        weight_kg=body.weight_kg,
        doctor_id=body.doctor_id,
    )
    return repo.save_patient(patient)


@router.post("/demo/seed", response_model=Patient, status_code=status.HTTP_201_CREATED)
async def seed_demo(repo: Repository = Depends(get_repo)) -> Patient:
    """Create a complete patient/doctor/family scenario for dashboard demos."""
    doctor = repo.save_doctor(
        Doctor(
            name="Dr. Elif Demir",
            contact_number="+90-555-0100",
            location="Istanbul",
            specialty="Cardiology",
            on_call_status=True,
        )
    )
    patient = repo.save_patient(
        Patient(
            name="Ahmet Yilmaz",
            contact_number="+90-555-0200",
            location="Kadikoy, Istanbul",
            age=67,
            height_cm=174,
            weight_kg=82,
            doctor_id=doctor.id,
            thresholds=PersonalizedThresholds(
                heart_rate_min=55,
                heart_rate_max=120,
                temperature_min=35.8,
                temperature_max=38.4,
            ),
        )
    )
    repo.save_family_member(
        FamilyMember(
            name="Mina Yilmaz",
            contact_number="+90-555-0300",
            relationship="daughter",
            patient_id=patient.id,
            location="Istanbul",
        )
    )
    for heart_rate, body_temperature, daily_steps in [
        (76, 36.6, 1240),
        (82, 36.7, 1308),
        (94, 36.8, 1416),
        (108, 37.0, 1534),
        (128, 37.4, 1602),
    ]:
        repo.append_record(
            HealthRecord(
                patient_id=patient.id,
                heart_rate=heart_rate,
                body_temperature=body_temperature,
                daily_steps=daily_steps,
            )
        )
    repo.append_event(
        Event(
            patient_id=patient.id,
            type=EventType.THRESHOLD_BREACH,
            message="Demo breach: HR=128 BPM (allowed 55-120)",
            metadata={"heart_rate": 128, "body_temperature": 37.4},
        )
    )
    return patient


@router.get("/patients", response_model=List[Patient])
async def list_patients(repo: Repository = Depends(get_repo)) -> List[Patient]:
    return repo.list_patients()


@router.get("/patients/{patient_id}", response_model=Patient)
async def get_patient(patient_id: str, repo: Repository = Depends(get_repo)) -> Patient:
    patient = repo.get_patient(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="patient not found")
    return patient


@router.get("/patients/{patient_id}/status", response_model=PatientStatus)
async def get_patient_status(
    patient_id: str,
    repo: Repository = Depends(get_repo),
    engine: AnomalyDetectionEngine = Depends(get_engine),
) -> PatientStatus:
    patient = repo.get_patient(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="patient not found")

    records = repo.recent_records(patient_id, limit=20)
    events = repo.recent_events(patient_id, limit=50)
    latest = records[0] if records else None
    recent_breach_count = sum(1 for e in events if e.type == EventType.THRESHOLD_BREACH)
    pending = engine.has_pending_verification(patient_id)
    deadline = engine.pending_verification_deadline(patient_id)
    seconds_remaining = None
    if deadline is not None:
        seconds_remaining = max(
            0, int((deadline - datetime.now(timezone.utc)).total_seconds())
        )

    risk_score = min(100, recent_breach_count * 12)
    summary = "No telemetry yet"
    if latest is not None:
        thresholds = patient.thresholds
        hr_breach = (
            latest.heart_rate < thresholds.heart_rate_min
            or latest.heart_rate > thresholds.heart_rate_max
        )
        temp_breach = (
            latest.body_temperature < thresholds.temperature_min
            or latest.body_temperature > thresholds.temperature_max
        )
        if hr_breach:
            risk_score += 35
        if temp_breach:
            risk_score += 35
        if not hr_breach and not temp_breach:
            summary = "Latest vitals are within personalized limits"
        else:
            parts = []
            if hr_breach:
                parts.append("heart rate outside range")
            if temp_breach:
                parts.append("temperature outside range")
            summary = " and ".join(parts).capitalize()

    if pending:
        risk_score += 20
        summary = "Waiting for patient verification"

    last_sos = next((e for e in events if e.type == EventType.SOS_TRIGGERED), None)
    last_confirm = next((e for e in events if e.type == EventType.VERIFICATION_CONFIRMED), None)
    sos_active = bool(
        last_sos and (last_confirm is None or last_sos.timestamp > last_confirm.timestamp)
    )
    if sos_active:
        risk_score = max(risk_score, 90)
        summary = "SOS escalation is active"

    call_attempted = any(e.type == EventType.CALL_ATTEMPTED for e in events)
    family_notifications_sent = sum(1 for e in events if e.type == EventType.FAMILY_NOTIFIED)
    doctor_notifications_sent = sum(1 for e in events if e.type == EventType.DOCTOR_NOTIFIED)

    risk_score = min(100, risk_score)
    if risk_score >= 75:
        risk_level = "critical"
    elif risk_score >= 35:
        risk_level = "warning"
    else:
        risk_level = "normal"

    return PatientStatus(
        patient_id=patient_id,
        risk_level=risk_level,
        risk_score=risk_score,
        summary=summary,
        latest_record=latest,
        verification_pending=pending,
        verification_deadline=deadline,
        seconds_remaining=seconds_remaining,
        recent_breach_count=recent_breach_count,
        sos_active=sos_active,
        call_attempted=call_attempted,
        family_notifications_sent=family_notifications_sent,
        doctor_notifications_sent=doctor_notifications_sent,
    )


@router.put("/patients/{patient_id}/thresholds", response_model=Patient)
async def update_thresholds(
    patient_id: str,
    thresholds: PersonalizedThresholds,
    repo: Repository = Depends(get_repo),
) -> Patient:
    patient = repo.get_patient(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="patient not found")
    patient.thresholds = thresholds
    return repo.save_patient(patient)


# ---------------------------------------------------------------------------
# Doctors & family
# ---------------------------------------------------------------------------

@router.post("/doctors", response_model=Doctor, status_code=status.HTTP_201_CREATED)
async def create_doctor(body: CreateDoctorRequest, repo: Repository = Depends(get_repo)) -> Doctor:
    doctor = Doctor(
        name=body.name,
        contact_number=body.contact_number,
        location=body.location,
        specialty=body.specialty,
        on_call_status=body.on_call_status,
    )
    return repo.save_doctor(doctor)


@router.get("/doctors", response_model=List[Doctor])
async def list_doctors(repo: Repository = Depends(get_repo)) -> List[Doctor]:
    return repo.list_doctors()


@router.get("/doctors/{doctor_id}", response_model=Doctor)
async def get_doctor(doctor_id: str, repo: Repository = Depends(get_repo)) -> Doctor:
    doctor = repo.get_doctor(doctor_id)
    if doctor is None:
        raise HTTPException(status_code=404, detail="doctor not found")
    return doctor


@router.get("/family/{patient_id}", response_model=List[FamilyMember])
async def list_family(patient_id: str, repo: Repository = Depends(get_repo)) -> List[FamilyMember]:
    return repo.list_family_for_patient(patient_id)


class AssignDoctorRequest(BaseModel):
    doctor_id: Optional[str] = None


@router.patch("/patients/{patient_id}/doctor", response_model=Patient)
async def assign_doctor(
    patient_id: str,
    body: AssignDoctorRequest,
    repo: Repository = Depends(get_repo),
) -> Patient:
    patient = repo.get_patient(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="patient not found")
    patient.doctor_id = body.doctor_id
    return repo.save_patient(patient)


@router.delete("/doctors/{doctor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doctor(doctor_id: str, repo: Repository = Depends(get_repo)):
    if not repo.delete_doctor(doctor_id):
        raise HTTPException(status_code=404, detail="doctor not found")


@router.delete("/family/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_family_member(member_id: str, repo: Repository = Depends(get_repo)):
    if not repo.delete_family_member(member_id):
        raise HTTPException(status_code=404, detail="family member not found")


@router.post("/family", response_model=FamilyMember, status_code=status.HTTP_201_CREATED)
async def create_family_member(
    body: CreateFamilyRequest, repo: Repository = Depends(get_repo)
) -> FamilyMember:
    if repo.get_patient(body.patient_id) is None:
        raise HTTPException(status_code=404, detail="patient not found")
    member = FamilyMember(
        name=body.name,
        contact_number=body.contact_number,
        location=body.location,
        relationship=body.relationship,
        patient_id=body.patient_id,
    )
    return repo.save_family_member(member)


# ---------------------------------------------------------------------------
# Telemetry, verification, snapshot
# ---------------------------------------------------------------------------

@router.post("/telemetry/{patient_id}")
async def push_telemetry(
    patient_id: str,
    body: TelemetryRequest,
    engine: AnomalyDetectionEngine = Depends(get_engine),
):
    record = HealthRecord(
        patient_id=patient_id,
        heart_rate=body.heart_rate,
        body_temperature=body.body_temperature,
        daily_steps=body.daily_steps,
    )
    try:
        reason = engine.process_record(record)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "record_id": record.id,
        "breach": reason.any,
        "detail": reason.detail,
        "verification_pending": engine.has_pending_verification(patient_id),
    }


@router.post("/verify/{patient_id}")
async def verify(patient_id: str, engine: AnomalyDetectionEngine = Depends(get_engine)):
    confirmed = engine.confirm_verification(patient_id)
    return {"confirmed": confirmed}


@router.post("/sos/{patient_id}/force", response_model=HealthSnapshot)
async def force_sos(
    patient_id: str,
    repo: Repository = Depends(get_repo),
    sos: SOSService = Depends(get_sos),
) -> HealthSnapshot:
    patient = repo.get_patient(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="patient not found")

    latest = repo.recent_records(patient_id, limit=1)
    if latest:
        record = latest[0]
        reason = BreachReason(
            heart_rate_breach=True,
            temperature_breach=False,
            detail=(
                "Manual demo escalation from dashboard; "
                f"latest HR={record.heart_rate}, Temp={record.body_temperature}"
            ),
        )
    else:
        reason = BreachReason(
            heart_rate_breach=True,
            temperature_breach=False,
            detail="Manual demo escalation from dashboard; no recent telemetry",
        )
    return sos.initiate_emergency_protocol(patient, reason)


@router.get("/snapshot/{patient_id}", response_model=HealthSnapshot)
async def get_snapshot(patient_id: str, sos: SOSService = Depends(get_sos)) -> HealthSnapshot:
    snap = sos.fetch_snapshot(patient_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="patient not found")
    return snap


@router.get("/events/{patient_id}", response_model=List[Event])
async def list_events(
    patient_id: str, limit: int = 50, repo: Repository = Depends(get_repo)
) -> List[Event]:
    return repo.recent_events(patient_id, limit=limit)


@router.get("/records/{patient_id}", response_model=List[HealthRecord])
async def list_records(
    patient_id: str, limit: int = 20, repo: Repository = Depends(get_repo)
) -> List[HealthRecord]:
    return repo.recent_records(patient_id, limit=limit)
