"""Domain models for VitalSense.

These mirror the UML class diagram in the progress report:
- Abstract User extended by Patient, Doctor, FamilyMember
- HealthRecord captures a single telemetry sample
- PersonalizedThresholds stores per-patient alert limits
- Event records what the system did and why (audit trail for doctors)
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid4().hex[:12]


# ---------------------------------------------------------------------------
# User hierarchy
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    FAMILY = "family"


class User(BaseModel):
    """Abstract base for all users in the system."""
    id: str = Field(default_factory=_new_id)
    name: str
    contact_number: str
    location: Optional[str] = None
    role: UserRole


class Doctor(User):
    role: UserRole = UserRole.DOCTOR
    specialty: str
    on_call_status: bool = False


class FamilyMember(User):
    role: UserRole = UserRole.FAMILY
    relationship: str
    patient_id: str  # which patient this contact belongs to


class PersonalizedThresholds(BaseModel):
    """Per-patient alert limits. Defaults are clinically conservative."""
    heart_rate_min: int = 50
    heart_rate_max: int = 120
    temperature_min: float = 35.5
    temperature_max: float = 39.0

    @field_validator("heart_rate_max")
    @classmethod
    def _hr_range(cls, v: int, info) -> int:
        lo = info.data.get("heart_rate_min", 0)
        if v <= lo:
            raise ValueError("heart_rate_max must be greater than heart_rate_min")
        return v

    @field_validator("temperature_max")
    @classmethod
    def _temp_range(cls, v: float, info) -> float:
        lo = info.data.get("temperature_min", 0.0)
        if v <= lo:
            raise ValueError("temperature_max must be greater than temperature_min")
        return v


class Patient(User):
    role: UserRole = UserRole.PATIENT
    age: int
    height_cm: float
    weight_kg: float
    thresholds: PersonalizedThresholds = Field(default_factory=PersonalizedThresholds)
    doctor_id: Optional[str] = None
    family_member_ids: List[str] = Field(default_factory=list)
    conditions: List[str] = Field(default_factory=list)
    medications: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)
    care_notes: Optional[str] = None

    @property
    def bmi(self) -> float:
        if self.height_cm <= 0:
            return 0.0
        h_m = self.height_cm / 100.0
        return round(self.weight_kg / (h_m * h_m), 2)


# ---------------------------------------------------------------------------
# Health data
# ---------------------------------------------------------------------------

class HealthRecord(BaseModel):
    """A single telemetry sample from a wearable."""
    id: str = Field(default_factory=_new_id)
    patient_id: str
    heart_rate: int
    body_temperature: float
    daily_steps: int = 0
    timestamp: datetime = Field(default_factory=_now)


class HealthSnapshot(BaseModel):
    """Bundle of recent records + patient context, shared with doctors during SOS."""
    patient: Patient
    recent_records: List[HealthRecord]
    triggered_at: datetime = Field(default_factory=_now)
    reason: str


# ---------------------------------------------------------------------------
# Events / audit log
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    THRESHOLD_BREACH = "threshold_breach"
    VERIFICATION_SENT = "verification_sent"
    VERIFICATION_CONFIRMED = "verification_confirmed"
    SOS_TRIGGERED = "sos_triggered"
    SOS_RESOLVED = "sos_resolved"
    FAMILY_NOTIFIED = "family_notified"
    DOCTOR_NOTIFIED = "doctor_notified"
    CALL_ATTEMPTED = "call_attempted"
    CHAT_TRIAGE = "chat_triage"


class Event(BaseModel):
    id: str = Field(default_factory=_new_id)
    patient_id: str
    type: EventType
    message: str
    timestamp: datetime = Field(default_factory=_now)
    metadata: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Health chat
# ---------------------------------------------------------------------------

class ChatRole(str, Enum):
    PATIENT = "patient"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatUrgency(str, Enum):
    ROUTINE = "routine"
    WATCH = "watch"
    URGENT = "urgent"
    EMERGENCY = "emergency"


class ChatRecommendedAction(str, Enum):
    NONE = "none"
    VERIFY = "verify"
    SHARE_DOCTOR = "share_doctor"
    TRIGGER_SOS = "trigger_sos"


class ChatMessage(BaseModel):
    id: str = Field(default_factory=_new_id)
    patient_id: str
    role: ChatRole
    content: str
    urgency: ChatUrgency = ChatUrgency.ROUTINE
    created_at: datetime = Field(default_factory=_now)
    metadata: dict = Field(default_factory=dict)


class ChatResult(BaseModel):
    reply: str
    urgency: ChatUrgency = ChatUrgency.ROUTINE
    recommended_action: ChatRecommendedAction = ChatRecommendedAction.NONE
    doctor_summary: str
    event_logged: bool = False
