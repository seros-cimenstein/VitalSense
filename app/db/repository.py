"""Repository: persistence abstraction over Firestore / in-memory.

The repository stores patients, doctors, family members, health records, and
events. Switching backends is controlled by the VITALSENSE_USE_FIRESTORE env
var; when unset, an in-memory dict-based store is used (which is what tests
and the demo script run against).
"""
from __future__ import annotations

import os
import threading
from collections import defaultdict
from typing import Dict, List, Optional

from app.models import (
    Doctor,
    Event,
    FamilyMember,
    HealthRecord,
    Patient,
)


class Repository:
    """Abstract interface every storage backend implements."""

    # patients
    def save_patient(self, patient: Patient) -> Patient: ...
    def get_patient(self, patient_id: str) -> Optional[Patient]: ...
    def list_patients(self) -> List[Patient]: ...
    def delete_patient(self, patient_id: str) -> bool: ...

    # doctors
    def save_doctor(self, doctor: Doctor) -> Doctor: ...
    def get_doctor(self, doctor_id: str) -> Optional[Doctor]: ...
    def list_doctors(self) -> List[Doctor]: ...
    def delete_doctor(self, doctor_id: str) -> bool: ...
    def delete_family_member(self, member_id: str) -> bool: ...

    # family
    def save_family_member(self, member: FamilyMember) -> FamilyMember: ...
    def get_family_member(self, member_id: str) -> Optional[FamilyMember]: ...
    def list_family_for_patient(self, patient_id: str) -> List[FamilyMember]: ...

    # health records
    def append_record(self, record: HealthRecord) -> HealthRecord: ...
    def recent_records(self, patient_id: str, limit: int = 20) -> List[HealthRecord]: ...

    # events
    def append_event(self, event: Event) -> Event: ...
    def recent_events(self, patient_id: str, limit: int = 50) -> List[Event]: ...


# ---------------------------------------------------------------------------
# In-memory implementation (default; used by tests and the demo)
# ---------------------------------------------------------------------------

class InMemoryRepository(Repository):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._patients: Dict[str, Patient] = {}
        self._doctors: Dict[str, Doctor] = {}
        self._family: Dict[str, FamilyMember] = {}
        self._records: Dict[str, List[HealthRecord]] = defaultdict(list)
        self._events: Dict[str, List[Event]] = defaultdict(list)

    # patients --------------------------------------------------------------
    def save_patient(self, patient: Patient) -> Patient:
        with self._lock:
            self._patients[patient.id] = patient
            return patient

    def get_patient(self, patient_id: str) -> Optional[Patient]:
        return self._patients.get(patient_id)

    def list_patients(self) -> List[Patient]:
        return list(self._patients.values())

    def delete_patient(self, patient_id: str) -> bool:
        with self._lock:
            if patient_id not in self._patients:
                return False
            del self._patients[patient_id]
            return True

    # doctors ---------------------------------------------------------------
    def save_doctor(self, doctor: Doctor) -> Doctor:
        with self._lock:
            self._doctors[doctor.id] = doctor
            return doctor

    def get_doctor(self, doctor_id: str) -> Optional[Doctor]:
        return self._doctors.get(doctor_id)

    def list_doctors(self) -> List[Doctor]:
        return list(self._doctors.values())

    def delete_doctor(self, doctor_id: str) -> bool:
        with self._lock:
            if doctor_id not in self._doctors:
                return False
            del self._doctors[doctor_id]
            return True

    # family ----------------------------------------------------------------
    def save_family_member(self, member: FamilyMember) -> FamilyMember:
        with self._lock:
            self._family[member.id] = member
            return member

    def get_family_member(self, member_id: str) -> Optional[FamilyMember]:
        return self._family.get(member_id)

    def delete_family_member(self, member_id: str) -> bool:
        with self._lock:
            if member_id not in self._family:
                return False
            del self._family[member_id]
            return True

    def list_family_for_patient(self, patient_id: str) -> List[FamilyMember]:
        return [m for m in self._family.values() if m.patient_id == patient_id]

    # records ---------------------------------------------------------------
    def append_record(self, record: HealthRecord) -> HealthRecord:
        with self._lock:
            self._records[record.patient_id].append(record)
            return record

    def recent_records(self, patient_id: str, limit: int = 20) -> List[HealthRecord]:
        records = self._records.get(patient_id, [])
        return sorted(records, key=lambda r: r.timestamp, reverse=True)[:limit]

    # events ----------------------------------------------------------------
    def append_event(self, event: Event) -> Event:
        with self._lock:
            self._events[event.patient_id].append(event)
            return event

    def recent_events(self, patient_id: str, limit: int = 50) -> List[Event]:
        events = self._events.get(patient_id, [])
        return sorted(events, key=lambda e: e.timestamp, reverse=True)[:limit]


# ---------------------------------------------------------------------------
# Firestore implementation
# ---------------------------------------------------------------------------

class FirestoreRepository(Repository):
    """Firestore-backed repository.

    Lazily imports firebase_admin so the in-memory path never pays the cost.
    Collections used: patients, doctors, family_members, health_records, events.
    """

    def __init__(self) -> None:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            cred_path = os.getenv(
                "GOOGLE_APPLICATION_CREDENTIALS", "firebase-credentials.json"
            )
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
            else:
                # Application Default Credentials
                firebase_admin.initialize_app()

        self._db = firestore.client()

    # patients --------------------------------------------------------------
    def save_patient(self, patient: Patient) -> Patient:
        self._db.collection("patients").document(patient.id).set(patient.model_dump(mode="json"))
        return patient

    def get_patient(self, patient_id: str) -> Optional[Patient]:
        snap = self._db.collection("patients").document(patient_id).get()
        return Patient(**snap.to_dict()) if snap.exists else None

    def list_patients(self) -> List[Patient]:
        return [Patient(**doc.to_dict()) for doc in self._db.collection("patients").stream()]

    def delete_patient(self, patient_id: str) -> bool:
        ref = self._db.collection("patients").document(patient_id)
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    # doctors ---------------------------------------------------------------
    def save_doctor(self, doctor: Doctor) -> Doctor:
        self._db.collection("doctors").document(doctor.id).set(doctor.model_dump(mode="json"))
        return doctor

    def get_doctor(self, doctor_id: str) -> Optional[Doctor]:
        snap = self._db.collection("doctors").document(doctor_id).get()
        return Doctor(**snap.to_dict()) if snap.exists else None

    def delete_doctor(self, doctor_id: str) -> bool:
        ref = self._db.collection("doctors").document(doctor_id)
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    def list_doctors(self) -> List[Doctor]:
        return [Doctor(**doc.to_dict()) for doc in self._db.collection("doctors").stream()]

    # family ----------------------------------------------------------------
    def save_family_member(self, member: FamilyMember) -> FamilyMember:
        self._db.collection("family_members").document(member.id).set(
            member.model_dump(mode="json")
        )
        return member

    def get_family_member(self, member_id: str) -> Optional[FamilyMember]:
        snap = self._db.collection("family_members").document(member_id).get()
        return FamilyMember(**snap.to_dict()) if snap.exists else None

    def delete_family_member(self, member_id: str) -> bool:
        ref = self._db.collection("family_members").document(member_id)
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    def list_family_for_patient(self, patient_id: str) -> List[FamilyMember]:
        docs = (
            self._db.collection("family_members")
            .where("patient_id", "==", patient_id)
            .stream()
        )
        return [FamilyMember(**d.to_dict()) for d in docs]

    # records ---------------------------------------------------------------
    def append_record(self, record: HealthRecord) -> HealthRecord:
        self._db.collection("health_records").document(record.id).set(
            record.model_dump(mode="json")
        )
        return record

    def recent_records(self, patient_id: str, limit: int = 20) -> List[HealthRecord]:
        from firebase_admin import firestore as _fs
        docs = (
            self._db.collection("health_records")
            .where("patient_id", "==", patient_id)
            .order_by("timestamp", direction=_fs.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        return [HealthRecord(**d.to_dict()) for d in docs]

    # events ----------------------------------------------------------------
    def append_event(self, event: Event) -> Event:
        self._db.collection("events").document(event.id).set(event.model_dump(mode="json"))
        return event

    def recent_events(self, patient_id: str, limit: int = 50) -> List[Event]:
        from firebase_admin import firestore as _fs
        docs = (
            self._db.collection("events")
            .where("patient_id", "==", patient_id)
            .order_by("timestamp", direction=_fs.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        return [Event(**d.to_dict()) for d in docs]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_repo_singleton: Optional[Repository] = None


def get_repository() -> Repository:
    """Return the configured repository, creating it on first call."""
    global _repo_singleton
    if _repo_singleton is not None:
        return _repo_singleton

    if os.getenv("VITALSENSE_USE_FIRESTORE") == "1":
        _repo_singleton = FirestoreRepository()
    else:
        _repo_singleton = InMemoryRepository()
    return _repo_singleton


def reset_repository() -> None:
    """Test helper — drops the singleton so the next call rebuilds it."""
    global _repo_singleton
    _repo_singleton = None
