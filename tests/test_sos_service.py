"""SOSService tests — verify that the emergency protocol does the right thing
even when called directly (i.e. independent of the anomaly engine)."""
from __future__ import annotations

from app.core.anomaly_engine import BreachReason
from app.models import EventType, HealthRecord
from app.services import NotificationService, SOSService


def test_sos_protocol_notifies_family_and_doctor(sos, repo, patient, notifier):
    repo.append_record(HealthRecord(patient_id=patient.id, heart_rate=130, body_temperature=37.5))
    reason = BreachReason(True, False, "HR=130 BPM (allowed 55-120)")

    snapshot = sos.initiate_emergency_protocol(patient, reason)

    assert snapshot.patient.id == patient.id
    assert len(snapshot.recent_records) >= 1

    types = [e.type for e in repo.recent_events(patient.id)]
    assert EventType.SOS_TRIGGERED in types
    assert EventType.CALL_ATTEMPTED in types
    assert EventType.FAMILY_NOTIFIED in types
    assert EventType.DOCTOR_NOTIFIED in types

    delivery_events = [
        e for e in repo.recent_events(patient.id)
        if e.type in {EventType.CALL_ATTEMPTED, EventType.FAMILY_NOTIFIED, EventType.DOCTOR_NOTIFIED}
    ]
    assert all(e.metadata["delivered"] is True for e in delivery_events)

    # Family + doctor SMS contents
    family_msg = next(m for c, m in notifier.sent if c == "+90-555-0300")
    assert patient.name in family_msg
    assert "İzmir" in family_msg  # location appears

    doctor_msg = next(m for c, m in notifier.sent if c == "+90-555-0100")
    assert "Snapshot" in doctor_msg or "snapshot" in doctor_msg


def test_sos_skips_doctor_when_off_call(sos, repo, patient, doctor, notifier):
    doctor.on_call_status = False
    repo.save_doctor(doctor)

    reason = BreachReason(True, False, "HR=130 BPM")
    sos.initiate_emergency_protocol(patient, reason)

    types = [e.type for e in repo.recent_events(patient.id)]
    assert EventType.FAMILY_NOTIFIED in types
    assert EventType.DOCTOR_NOTIFIED not in types


def test_sos_uses_snapshot_link_factory(repo, patient, notifier):
    sos = SOSService(
        repo,
        NotificationService(notifier),
        snapshot_link_factory=lambda patient_id: f"https://example.test/doctor/{patient_id}?token=abc",
    )
    reason = BreachReason(True, False, "HR=130 BPM")

    sos.initiate_emergency_protocol(patient, reason)

    doctor_event = next(
        e for e in repo.recent_events(patient.id)
        if e.type == EventType.DOCTOR_NOTIFIED
    )
    expected = f"https://example.test/doctor/{patient.id}?token=abc"
    assert doctor_event.metadata["snapshot_url"] == expected
    doctor_msg = next(m for c, m in notifier.sent if c == "+90-555-0100")
    assert expected in doctor_msg


def test_fetch_snapshot_returns_none_for_unknown_patient(sos):
    assert sos.fetch_snapshot("unknown") is None


def test_fetch_snapshot_includes_recent_records(sos, repo, patient):
    for hr in (75, 80, 85):
        repo.append_record(HealthRecord(
            patient_id=patient.id, heart_rate=hr, body_temperature=36.7
        ))
    snap = sos.fetch_snapshot(patient.id)
    assert snap is not None
    assert len(snap.recent_records) == 3
    # most-recent first
    assert snap.recent_records[0].heart_rate == 85
