"""Shared fixtures: clean repository + a wired-up engine for each test."""
from __future__ import annotations

import sys
from pathlib import Path

# Make ``app`` importable when running ``pytest`` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.core import AnomalyDetectionEngine
from app.db.repository import InMemoryRepository
from app.models import (
    Doctor,
    FamilyMember,
    Patient,
    PersonalizedThresholds,
)
from app.services import ConsoleNotifier, NotificationService, SOSService


class ImmediateTimer:
    """Test double for threading.Timer that never actually waits.

    The engine only calls .start(), .cancel(); we expose force() so tests
    decide when 'time has passed'.
    """

    def __init__(self, secs: float, callback):
        self.secs = secs
        self.callback = callback
        self.cancelled = False
        self.fired = False
        self.daemon = False

    def start(self) -> None:
        pass  # don't actually start a thread

    def cancel(self) -> None:
        self.cancelled = True

    def force(self) -> None:
        if not self.cancelled and not self.fired:
            self.fired = True
            self.callback()


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture(autouse=True)
def _local_chat_provider(monkeypatch):
    monkeypatch.setenv("VITALSENSE_CHAT_MODEL_PROVIDER", "local")


@pytest.fixture
def notifier() -> ConsoleNotifier:
    return ConsoleNotifier()


@pytest.fixture
def sos(repo, notifier) -> SOSService:
    return SOSService(repo, NotificationService(notifier))


@pytest.fixture
def created_timers() -> list[ImmediateTimer]:
    return []


@pytest.fixture
def engine(repo, sos, created_timers, notifier) -> AnomalyDetectionEngine:
    def factory(secs: float, cb):
        t = ImmediateTimer(secs, cb)
        created_timers.append(t)
        return t

    prompt_service = NotificationService(notifier)

    def verification_prompt(patient, reason, timeout_seconds: float) -> bool:
        return prompt_service.send_verification_prompt(
            patient.contact_number,
            patient.name,
            reason.detail,
            int(timeout_seconds),
        )

    return AnomalyDetectionEngine(
        repo,
        sos,
        verification_timeout=60.0,
        timer_factory=factory,
        verification_notifier=verification_prompt,
    )


@pytest.fixture
def doctor(repo) -> Doctor:
    return repo.save_doctor(
        Doctor(
            name="Dr. Aylin Demir",
            contact_number="+90-555-0100",
            specialty="Cardiology",
            on_call_status=True,
        )
    )


@pytest.fixture
def patient(repo, doctor) -> Patient:
    p = repo.save_patient(
        Patient(
            name="Ahmet Yılmaz",
            contact_number="+90-555-0200",
            location="İzmir",
            age=72,
            height_cm=174.0,
            weight_kg=78.0,
            thresholds=PersonalizedThresholds(
                heart_rate_min=55,
                heart_rate_max=120,
                temperature_min=35.8,
                temperature_max=38.5,
            ),
            doctor_id=doctor.id,
        )
    )
    repo.save_family_member(
        FamilyMember(
            name="Mehmet Yılmaz",
            contact_number="+90-555-0300",
            relationship="son",
            patient_id=p.id,
        )
    )
    return p
