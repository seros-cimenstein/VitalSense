"""Tests for FirestoreRepository using mocked firebase_admin."""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from app.models import Doctor, Event, EventType, FamilyMember, HealthRecord, Patient


def _make_doc_snap(data: dict, exists: bool = True):
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data
    return snap


def _build_firestore_repo():
    """Construct FirestoreRepository with fully mocked firebase_admin."""
    db_mock = MagicMock()

    firebase_mock = MagicMock()
    firebase_mock._apps = {"default": True}  # pretend already initialised

    fs_module = MagicMock()
    fs_module.client.return_value = db_mock
    fs_module.Query.DESCENDING = "DESCENDING"
    firebase_mock.firestore = fs_module

    credentials_mock = MagicMock()
    firebase_mock.credentials = credentials_mock

    with patch.dict(
        sys.modules,
        {
            "firebase_admin": firebase_mock,
            "firebase_admin.firestore": fs_module,
            "firebase_admin.credentials": credentials_mock,
        },
    ):
        from app.db.repository import FirestoreRepository
        repo = FirestoreRepository.__new__(FirestoreRepository)
        repo._db = db_mock

    return repo, db_mock


# ---------------------------------------------------------------------------
# Patient CRUD
# ---------------------------------------------------------------------------

class TestFirestorePatient:
    def setup_method(self):
        self.repo, self.db = _build_firestore_repo()

    def _col(self, name):
        return self.db.collection.return_value

    def test_save_patient_calls_set(self):
        patient = Patient(name="Ali", contact_number="+90-555-0001", age=50,
                          height_cm=175, weight_kg=70)
        self.repo.save_patient(patient)
        self.db.collection.assert_called_with("patients")
        self.db.collection().document.assert_called_with(patient.id)
        self.db.collection().document().set.assert_called_once()

    def test_get_patient_found(self):
        patient = Patient(name="Ali", contact_number="+90-555-0001", age=50,
                          height_cm=175, weight_kg=70)
        snap = _make_doc_snap(patient.model_dump(mode="json"))
        self.db.collection().document().get.return_value = snap
        result = self.repo.get_patient(patient.id)
        assert result is not None
        assert result.name == "Ali"

    def test_get_patient_not_found(self):
        snap = _make_doc_snap({}, exists=False)
        self.db.collection().document().get.return_value = snap
        assert self.repo.get_patient("nonexistent") is None

    def test_delete_patient_found(self):
        snap = _make_doc_snap({"id": "x"}, exists=True)
        self.db.collection().document().get.return_value = snap
        result = self.repo.delete_patient("x")
        assert result is True
        self.db.collection().document().delete.assert_called_once()

    def test_delete_patient_not_found(self):
        snap = _make_doc_snap({}, exists=False)
        self.db.collection().document().get.return_value = snap
        assert self.repo.delete_patient("missing") is False

    def test_list_patients(self):
        p = Patient(name="Zeynep", contact_number="+90-555-0002", age=30,
                    height_cm=162, weight_kg=55)
        self.db.collection().stream.return_value = [_make_doc_snap(p.model_dump(mode="json"))]
        patients = self.repo.list_patients()
        assert len(patients) == 1
        assert patients[0].name == "Zeynep"


# ---------------------------------------------------------------------------
# Doctor CRUD
# ---------------------------------------------------------------------------

class TestFirestoreDoctor:
    def setup_method(self):
        self.repo, self.db = _build_firestore_repo()

    def test_save_doctor(self):
        doc = Doctor(name="Dr. Elif", contact_number="+90-555-0100",
                     specialty="Cardiology", on_call_status=True)
        self.repo.save_doctor(doc)
        self.db.collection.assert_called_with("doctors")
        self.db.collection().document().set.assert_called_once()

    def test_get_doctor_found(self):
        doc = Doctor(name="Dr. Elif", contact_number="+90-555-0100",
                     specialty="Cardiology", on_call_status=True)
        snap = _make_doc_snap(doc.model_dump(mode="json"))
        self.db.collection().document().get.return_value = snap
        result = self.repo.get_doctor(doc.id)
        assert result is not None
        assert result.specialty == "Cardiology"

    def test_delete_doctor_found(self):
        snap = _make_doc_snap({"id": "d1"}, exists=True)
        self.db.collection().document().get.return_value = snap
        assert self.repo.delete_doctor("d1") is True

    def test_delete_doctor_missing(self):
        snap = _make_doc_snap({}, exists=False)
        self.db.collection().document().get.return_value = snap
        assert self.repo.delete_doctor("missing") is False

    def test_list_doctors(self):
        doc = Doctor(name="Dr. Mert", contact_number="+90-555-0200",
                     specialty="Neurology", on_call_status=False)
        self.db.collection().stream.return_value = [_make_doc_snap(doc.model_dump(mode="json"))]
        doctors = self.repo.list_doctors()
        assert len(doctors) == 1
        assert doctors[0].specialty == "Neurology"


# ---------------------------------------------------------------------------
# Family member CRUD
# ---------------------------------------------------------------------------

class TestFirestoreFamilyMember:
    def setup_method(self):
        self.repo, self.db = _build_firestore_repo()

    def test_save_family_member(self):
        member = FamilyMember(name="Selin", contact_number="+90-555-0300",
                              relationship="daughter", patient_id="p1")
        self.repo.save_family_member(member)
        self.db.collection.assert_called_with("family_members")
        self.db.collection().document().set.assert_called_once()

    def test_delete_family_member_found(self):
        snap = _make_doc_snap({"id": "f1"}, exists=True)
        self.db.collection().document().get.return_value = snap
        assert self.repo.delete_family_member("f1") is True

    def test_list_family_for_patient(self):
        member = FamilyMember(name="Selin", contact_number="+90-555-0300",
                              relationship="daughter", patient_id="p1")
        chain = self.db.collection().where().stream
        chain.return_value = [_make_doc_snap(member.model_dump(mode="json"))]
        results = self.repo.list_family_for_patient("p1")
        assert len(results) == 1
        assert results[0].relationship == "daughter"


# ---------------------------------------------------------------------------
# Health records
# ---------------------------------------------------------------------------

class TestFirestoreHealthRecords:
    def setup_method(self):
        self.repo, self.db = _build_firestore_repo()

    def test_append_record(self):
        record = HealthRecord(patient_id="p1", heart_rate=75,
                              body_temperature=36.6, daily_steps=500)
        self.repo.append_record(record)
        self.db.collection.assert_called_with("health_records")
        self.db.collection().document().set.assert_called_once()

    def test_recent_records(self):
        record = HealthRecord(patient_id="p1", heart_rate=80,
                              body_temperature=36.8, daily_steps=1000)
        chain = self.db.collection().where().order_by().limit().stream
        chain.return_value = [_make_doc_snap(record.model_dump(mode="json"))]
        results = self.repo.recent_records("p1", limit=5)
        assert len(results) == 1
        assert results[0].heart_rate == 80


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class TestFirestoreEvents:
    def setup_method(self):
        self.repo, self.db = _build_firestore_repo()

    def test_append_event(self):
        event = Event(patient_id="p1", type=EventType.SOS_TRIGGERED,
                      message="SOS fired")
        self.repo.append_event(event)
        self.db.collection.assert_called_with("events")
        self.db.collection().document().set.assert_called_once()

    def test_recent_events(self):
        event = Event(patient_id="p1", type=EventType.THRESHOLD_BREACH,
                      message="HR high")
        chain = self.db.collection().where().order_by().limit().stream
        chain.return_value = [_make_doc_snap(event.model_dump(mode="json"))]
        results = self.repo.recent_events("p1", limit=10)
        assert len(results) == 1
        assert results[0].type == EventType.THRESHOLD_BREACH
