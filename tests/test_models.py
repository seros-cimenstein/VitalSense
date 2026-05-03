"""Tests for domain models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import (
    Doctor,
    HealthRecord,
    Patient,
    PersonalizedThresholds,
)


def test_patient_bmi_is_correct():
    p = Patient(
        name="Test",
        contact_number="x",
        age=30,
        height_cm=180.0,
        weight_kg=81.0,
    )
    # 81 / 1.8^2 = 25.0
    assert p.bmi == 25.0


def test_patient_bmi_handles_zero_height():
    p = Patient(name="Test", contact_number="x", age=30, height_cm=0, weight_kg=70)
    assert p.bmi == 0.0


def test_patient_clinical_profile_defaults_to_empty():
    p = Patient(name="Test", contact_number="x", age=30, height_cm=180, weight_kg=81)
    assert p.conditions == []
    assert p.medications == []
    assert p.allergies == []
    assert p.care_notes is None


def test_thresholds_reject_inverted_hr_range():
    with pytest.raises(ValidationError):
        PersonalizedThresholds(heart_rate_min=120, heart_rate_max=60)


def test_thresholds_reject_inverted_temp_range():
    with pytest.raises(ValidationError):
        PersonalizedThresholds(temperature_min=39.0, temperature_max=36.0)


def test_default_thresholds_are_clinical():
    t = PersonalizedThresholds()
    assert t.heart_rate_min == 50
    assert t.heart_rate_max == 120
    assert 35.0 < t.temperature_min < 36.0
    assert 38.0 < t.temperature_max < 40.0


def test_health_record_round_trips_through_pydantic():
    r = HealthRecord(patient_id="p1", heart_rate=72, body_temperature=36.6)
    payload = r.model_dump(mode="json")
    rebuilt = HealthRecord(**payload)
    assert rebuilt.patient_id == r.patient_id
    assert rebuilt.heart_rate == r.heart_rate
    assert rebuilt.body_temperature == r.body_temperature


def test_doctor_inherits_user_role():
    d = Doctor(name="D", contact_number="x", specialty="cardio")
    assert d.role.value == "doctor"
    assert d.specialty == "cardio"
    # default on_call_status is False until explicitly set
    assert d.on_call_status is False
