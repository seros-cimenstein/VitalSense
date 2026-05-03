"""SQLite repository tests."""
from __future__ import annotations

from app.db.repository import SQLiteRepository
from app.models import Doctor, Event, EventType, FamilyMember, HealthRecord, Patient


def test_sqlite_repository_persists_core_data(tmp_path):
    db_path = tmp_path / "vitalsense.db"
    repo = SQLiteRepository(db_path)

    doctor = repo.save_doctor(
        Doctor(
            name="Dr. Persist",
            contact_number="+90-555-0100",
            specialty="Cardiology",
            on_call_status=True,
        )
    )
    patient = repo.save_patient(
        Patient(
            name="Persistent Patient",
            contact_number="+90-555-0200",
            age=66,
            height_cm=172,
            weight_kg=74,
            doctor_id=doctor.id,
        )
    )
    member = repo.save_family_member(
        FamilyMember(
            name="Family Persist",
            contact_number="+90-555-0300",
            relationship="daughter",
            patient_id=patient.id,
        )
    )
    record = repo.append_record(
        HealthRecord(
            patient_id=patient.id,
            heart_rate=88,
            body_temperature=36.8,
            daily_steps=840,
        )
    )
    event = repo.append_event(
        Event(
            patient_id=patient.id,
            type=EventType.THRESHOLD_BREACH,
            message="Persisted event",
        )
    )
    repo.close()

    reopened = SQLiteRepository(db_path)
    assert reopened.get_doctor(doctor.id).name == "Dr. Persist"
    assert reopened.get_patient(patient.id).name == "Persistent Patient"
    assert reopened.list_family_for_patient(patient.id)[0].id == member.id
    assert reopened.recent_records(patient.id)[0].id == record.id
    assert reopened.recent_events(patient.id)[0].id == event.id
    reopened.close()


def test_sqlite_repository_deletes_records_by_table(tmp_path):
    repo = SQLiteRepository(tmp_path / "vitalsense.db")
    patient = repo.save_patient(
        Patient(
            name="Delete Me",
            contact_number="+90-555-0200",
            age=45,
            height_cm=170,
            weight_kg=70,
        )
    )
    member = repo.save_family_member(
        FamilyMember(
            name="Contact",
            contact_number="+90-555-0300",
            relationship="spouse",
            patient_id=patient.id,
        )
    )

    assert repo.delete_family_member(member.id) is True
    assert repo.delete_family_member(member.id) is False
    assert repo.delete_patient(patient.id) is True
    assert repo.delete_patient(patient.id) is False
    repo.close()
