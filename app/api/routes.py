"""HTTP API routes for VitalSense."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_engine, get_repo, get_sos
from app.core import AnomalyDetectionEngine
from app.db import Repository
from app.models import (
    Doctor,
    Event,
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


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@router.post("/patients", response_model=Patient, status_code=status.HTTP_201_CREATED)
def create_patient(body: CreatePatientRequest, repo: Repository = Depends(get_repo)) -> Patient:
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


@router.get("/patients", response_model=List[Patient])
def list_patients(repo: Repository = Depends(get_repo)) -> List[Patient]:
    return repo.list_patients()


@router.get("/patients/{patient_id}", response_model=Patient)
def get_patient(patient_id: str, repo: Repository = Depends(get_repo)) -> Patient:
    patient = repo.get_patient(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="patient not found")
    return patient


@router.put("/patients/{patient_id}/thresholds", response_model=Patient)
def update_thresholds(
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
def create_doctor(body: CreateDoctorRequest, repo: Repository = Depends(get_repo)) -> Doctor:
    doctor = Doctor(
        name=body.name,
        contact_number=body.contact_number,
        location=body.location,
        specialty=body.specialty,
        on_call_status=body.on_call_status,
    )
    return repo.save_doctor(doctor)


@router.get("/doctors", response_model=List[Doctor])
def list_doctors(repo: Repository = Depends(get_repo)) -> List[Doctor]:
    return repo.list_doctors()


@router.get("/doctors/{doctor_id}", response_model=Doctor)
def get_doctor(doctor_id: str, repo: Repository = Depends(get_repo)) -> Doctor:
    doctor = repo.get_doctor(doctor_id)
    if doctor is None:
        raise HTTPException(status_code=404, detail="doctor not found")
    return doctor


@router.get("/family/{patient_id}", response_model=List[FamilyMember])
def list_family(patient_id: str, repo: Repository = Depends(get_repo)) -> List[FamilyMember]:
    return repo.list_family_for_patient(patient_id)


class AssignDoctorRequest(BaseModel):
    doctor_id: Optional[str] = None


@router.patch("/patients/{patient_id}/doctor", response_model=Patient)
def assign_doctor(
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
def delete_doctor(doctor_id: str, repo: Repository = Depends(get_repo)):
    if not repo.delete_doctor(doctor_id):
        raise HTTPException(status_code=404, detail="doctor not found")


@router.delete("/family/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_family_member(member_id: str, repo: Repository = Depends(get_repo)):
    if not repo.delete_family_member(member_id):
        raise HTTPException(status_code=404, detail="family member not found")


@router.post("/family", response_model=FamilyMember, status_code=status.HTTP_201_CREATED)
def create_family_member(
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
def push_telemetry(
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
def verify(patient_id: str, engine: AnomalyDetectionEngine = Depends(get_engine)):
    confirmed = engine.confirm_verification(patient_id)
    return {"confirmed": confirmed}


@router.get("/snapshot/{patient_id}", response_model=HealthSnapshot)
def get_snapshot(patient_id: str, sos: SOSService = Depends(get_sos)) -> HealthSnapshot:
    snap = sos.fetch_snapshot(patient_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="patient not found")
    return snap


@router.get("/events/{patient_id}", response_model=List[Event])
def list_events(
    patient_id: str, limit: int = 50, repo: Repository = Depends(get_repo)
) -> List[Event]:
    return repo.recent_events(patient_id, limit=limit)


@router.get("/records/{patient_id}", response_model=List[HealthRecord])
def list_records(
    patient_id: str, limit: int = 20, repo: Repository = Depends(get_repo)
) -> List[HealthRecord]:
    return repo.recent_records(patient_id, limit=limit)
