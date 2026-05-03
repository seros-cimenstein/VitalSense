"""Repository: persistence abstraction over SQLite / Firestore / in-memory.

The repository stores patients, doctors, family members, health records, and
events. SQLite is the default backend so the dashboard keeps data between
process restarts without external credentials. Firestore and in-memory remain
available through environment configuration.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path
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


def _dump(model) -> str:
    return json.dumps(model.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)


def _load(model_cls, payload: str):
    return model_cls(**json.loads(payload))


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
# SQLite implementation (default runtime persistence)
# ---------------------------------------------------------------------------

class SQLiteRepository(Repository):
    """SQLite-backed repository for local and hosted demos.

    Domain objects are stored as JSON blobs plus indexed lookup columns. That
    keeps the repository small while still giving us real persistence and
    efficient patient-scoped queries for records, events, and family members.
    """

    def __init__(self, db_path: str | os.PathLike[str] = "data/vitalsense.db") -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS patients (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS doctors (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS family_members (
                    id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_family_patient
                    ON family_members(patient_id);
                CREATE TABLE IF NOT EXISTS health_records (
                    id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_records_patient_time
                    ON health_records(patient_id, timestamp DESC);
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_patient_time
                    ON events(patient_id, timestamp DESC);
                """
            )
            self._conn.commit()

    def _upsert(self, table: str, values: dict[str, object], update_columns: list[str]) -> None:
        columns = list(values.keys())
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{column}=excluded.{column}" for column in update_columns)
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}"
        )
        with self._lock:
            self._conn.execute(sql, [values[column] for column in columns])
            self._conn.commit()

    def _get_by_id(self, table: str, model_cls, item_id: str):
        with self._lock:
            row = self._conn.execute(
                f"SELECT data FROM {table} WHERE id = ?",
                (item_id,),
            ).fetchone()
        return _load(model_cls, row["data"]) if row else None

    def _list_all(self, table: str, model_cls):
        with self._lock:
            rows = self._conn.execute(f"SELECT data FROM {table} ORDER BY rowid").fetchall()
        return [_load(model_cls, row["data"]) for row in rows]

    # patients --------------------------------------------------------------
    def save_patient(self, patient: Patient) -> Patient:
        self._upsert("patients", {"id": patient.id, "data": _dump(patient)}, ["data"])
        return patient

    def get_patient(self, patient_id: str) -> Optional[Patient]:
        return self._get_by_id("patients", Patient, patient_id)

    def list_patients(self) -> List[Patient]:
        return self._list_all("patients", Patient)

    def delete_patient(self, patient_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    # doctors ---------------------------------------------------------------
    def save_doctor(self, doctor: Doctor) -> Doctor:
        self._upsert("doctors", {"id": doctor.id, "data": _dump(doctor)}, ["data"])
        return doctor

    def get_doctor(self, doctor_id: str) -> Optional[Doctor]:
        return self._get_by_id("doctors", Doctor, doctor_id)

    def list_doctors(self) -> List[Doctor]:
        return self._list_all("doctors", Doctor)

    def delete_doctor(self, doctor_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    # family ----------------------------------------------------------------
    def save_family_member(self, member: FamilyMember) -> FamilyMember:
        self._upsert(
            "family_members",
            {"id": member.id, "patient_id": member.patient_id, "data": _dump(member)},
            ["patient_id", "data"],
        )
        return member

    def get_family_member(self, member_id: str) -> Optional[FamilyMember]:
        return self._get_by_id("family_members", FamilyMember, member_id)

    def delete_family_member(self, member_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM family_members WHERE id = ?",
                (member_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def list_family_for_patient(self, patient_id: str) -> List[FamilyMember]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM family_members WHERE patient_id = ? ORDER BY rowid",
                (patient_id,),
            ).fetchall()
        return [_load(FamilyMember, row["data"]) for row in rows]

    # records ---------------------------------------------------------------
    def append_record(self, record: HealthRecord) -> HealthRecord:
        self._upsert(
            "health_records",
            {
                "id": record.id,
                "patient_id": record.patient_id,
                "timestamp": record.timestamp.isoformat(),
                "data": _dump(record),
            },
            ["patient_id", "timestamp", "data"],
        )
        return record

    def recent_records(self, patient_id: str, limit: int = 20) -> List[HealthRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT data FROM health_records
                WHERE patient_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (patient_id, limit),
            ).fetchall()
        return [_load(HealthRecord, row["data"]) for row in rows]

    # events ----------------------------------------------------------------
    def append_event(self, event: Event) -> Event:
        self._upsert(
            "events",
            {
                "id": event.id,
                "patient_id": event.patient_id,
                "timestamp": event.timestamp.isoformat(),
                "data": _dump(event),
            },
            ["patient_id", "timestamp", "data"],
        )
        return event

    def recent_events(self, patient_id: str, limit: int = 50) -> List[Event]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT data FROM events
                WHERE patient_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (patient_id, limit),
            ).fetchall()
        return [_load(Event, row["data"]) for row in rows]


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

    backend = os.getenv("VITALSENSE_REPOSITORY", "").lower()
    if os.getenv("VITALSENSE_USE_FIRESTORE") == "1" or backend == "firestore":
        _repo_singleton = FirestoreRepository()
    elif backend == "memory":
        _repo_singleton = InMemoryRepository()
    else:
        db_path = os.getenv("VITALSENSE_DB_PATH", "data/vitalsense.db")
        _repo_singleton = SQLiteRepository(db_path)
    return _repo_singleton


def reset_repository() -> None:
    """Test helper — drops the singleton so the next call rebuilds it."""
    global _repo_singleton
    if isinstance(_repo_singleton, SQLiteRepository):
        _repo_singleton.close()
    _repo_singleton = None
