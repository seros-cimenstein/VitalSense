"""Tests for AnomalyDetectionEngine: threshold breach detection and the
verification → SOS escalation flow."""
from __future__ import annotations

from app.core.anomaly_engine import evaluate_thresholds
from app.models import EventType, HealthRecord, PersonalizedThresholds


# ---------------------------------------------------------------------------
# Pure threshold evaluation
# ---------------------------------------------------------------------------

def test_evaluate_thresholds_within_range():
    t = PersonalizedThresholds(heart_rate_min=60, heart_rate_max=100,
                               temperature_min=36.0, temperature_max=38.0)
    r = HealthRecord(patient_id="p", heart_rate=80, body_temperature=37.0)
    reason = evaluate_thresholds(r, t)
    assert reason.any is False
    assert reason.heart_rate_breach is False
    assert reason.temperature_breach is False


def test_evaluate_thresholds_high_hr_breach():
    t = PersonalizedThresholds(heart_rate_min=60, heart_rate_max=100,
                               temperature_min=36.0, temperature_max=38.0)
    r = HealthRecord(patient_id="p", heart_rate=130, body_temperature=37.0)
    reason = evaluate_thresholds(r, t)
    assert reason.heart_rate_breach is True
    assert reason.temperature_breach is False
    assert "130" in reason.detail


def test_evaluate_thresholds_low_hr_breach():
    t = PersonalizedThresholds(heart_rate_min=60, heart_rate_max=100)
    r = HealthRecord(patient_id="p", heart_rate=40, body_temperature=37.0)
    reason = evaluate_thresholds(r, t)
    assert reason.heart_rate_breach is True


def test_evaluate_thresholds_temperature_breach():
    t = PersonalizedThresholds()
    r = HealthRecord(patient_id="p", heart_rate=80, body_temperature=39.5)
    reason = evaluate_thresholds(r, t)
    assert reason.temperature_breach is True
    assert reason.heart_rate_breach is False


def test_evaluate_thresholds_both_breaches_concatenated():
    t = PersonalizedThresholds()
    r = HealthRecord(patient_id="p", heart_rate=160, body_temperature=40.0)
    reason = evaluate_thresholds(r, t)
    assert reason.heart_rate_breach
    assert reason.temperature_breach
    assert ";" in reason.detail


# ---------------------------------------------------------------------------
# Engine + repository + SOS integration (with stub timer)
# ---------------------------------------------------------------------------

def test_engine_persists_record_and_emits_no_event_when_normal(engine, repo, patient):
    record = HealthRecord(patient_id=patient.id, heart_rate=80, body_temperature=36.7)
    engine.process_record(record)

    assert len(repo.recent_records(patient.id)) == 1
    assert repo.recent_events(patient.id) == []
    assert engine.has_pending_verification(patient.id) is False


def test_engine_starts_verification_on_breach(engine, repo, patient):
    record = HealthRecord(patient_id=patient.id, heart_rate=130, body_temperature=37.0)
    engine.process_record(record)

    assert engine.has_pending_verification(patient.id) is True
    types = [e.type for e in repo.recent_events(patient.id)]
    assert EventType.THRESHOLD_BREACH in types
    assert EventType.VERIFICATION_SENT in types


def test_engine_does_not_stack_verifications_for_same_patient(engine, patient, created_timers):
    engine.process_record(HealthRecord(patient_id=patient.id, heart_rate=130, body_temperature=37.0))
    engine.process_record(HealthRecord(patient_id=patient.id, heart_rate=140, body_temperature=37.2))
    # Only one timer should be active for this patient
    assert sum(1 for t in created_timers if not t.cancelled and not t.fired) == 1


def test_confirmation_cancels_sos(engine, repo, patient, created_timers):
    engine.process_record(HealthRecord(patient_id=patient.id, heart_rate=130, body_temperature=37.0))
    assert engine.has_pending_verification(patient.id)

    confirmed = engine.confirm_verification(patient.id)
    assert confirmed is True
    assert engine.has_pending_verification(patient.id) is False
    assert created_timers[-1].cancelled is True

    types = [e.type for e in repo.recent_events(patient.id)]
    assert EventType.VERIFICATION_CONFIRMED in types
    assert EventType.SOS_TRIGGERED not in types


def test_confirmation_with_no_pending_returns_false(engine, patient):
    assert engine.confirm_verification(patient.id) is False


def test_timeout_triggers_full_sos_protocol(engine, repo, patient, created_timers, notifier):
    engine.process_record(HealthRecord(patient_id=patient.id, heart_rate=130, body_temperature=37.0))

    # simulate the verification timer firing
    created_timers[-1].force()

    assert engine.has_pending_verification(patient.id) is False
    types = [e.type for e in repo.recent_events(patient.id)]
    assert EventType.SOS_TRIGGERED in types
    assert EventType.FAMILY_NOTIFIED in types
    assert EventType.DOCTOR_NOTIFIED in types

    # the family member's number was notified
    sent_to = [contact for contact, _ in notifier.sent]
    assert "+90-555-0300" in sent_to  # son
    # the on-call doctor's number was notified
    assert "+90-555-0100" in sent_to


def test_unknown_patient_raises(engine):
    record = HealthRecord(patient_id="nope", heart_rate=80, body_temperature=37.0)
    try:
        engine.process_record(record)
    except ValueError as e:
        assert "nope" in str(e)
    else:
        raise AssertionError("expected ValueError")
