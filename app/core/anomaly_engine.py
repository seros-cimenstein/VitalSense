"""AnomalyDetectionEngine — the event router at the heart of the system.

Responsibilities:
1. Ingest a HealthRecord from a wearable adapter.
2. Compare it against the patient's PersonalizedThresholds.
3. On breach, send a verification prompt and start a timer.
4. If the patient confirms in time, cancel the timer.
5. If the timer expires, hand off to the SOSService.

The engine is intentionally storage-agnostic: it receives a Repository and an
SOSService via constructor, so it stays unit-testable.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional

from app.db import Repository
from app.models import (
    Event,
    EventType,
    HealthRecord,
    Patient,
    PersonalizedThresholds,
)


# Default verification window — the report says 60 seconds for Ahmet's scenario.
DEFAULT_VERIFICATION_TIMEOUT_SECONDS: float = 60.0


@dataclass(frozen=True)
class BreachReason:
    """Why a record breached thresholds — used in messages and snapshots."""
    heart_rate_breach: bool
    temperature_breach: bool
    detail: str

    @property
    def any(self) -> bool:
        return self.heart_rate_breach or self.temperature_breach


def evaluate_thresholds(
    record: HealthRecord, thresholds: PersonalizedThresholds
) -> BreachReason:
    """Pure function: does this record breach the patient's thresholds?"""
    hr_breach = (
        record.heart_rate < thresholds.heart_rate_min
        or record.heart_rate > thresholds.heart_rate_max
    )
    temp_breach = (
        record.body_temperature < thresholds.temperature_min
        or record.body_temperature > thresholds.temperature_max
    )

    parts = []
    if hr_breach:
        parts.append(
            f"HR={record.heart_rate} BPM (allowed "
            f"{thresholds.heart_rate_min}-{thresholds.heart_rate_max})"
        )
    if temp_breach:
        parts.append(
            f"Temp={record.body_temperature}°C (allowed "
            f"{thresholds.temperature_min}-{thresholds.temperature_max})"
        )

    return BreachReason(
        heart_rate_breach=hr_breach,
        temperature_breach=temp_breach,
        detail="; ".join(parts) if parts else "within range",
    )


class AnomalyDetectionEngine:
    def __init__(
        self,
        repo: Repository,
        sos_service,  # forward ref — SOSService imported in services
        verification_timeout: float = DEFAULT_VERIFICATION_TIMEOUT_SECONDS,
        timer_factory: Optional[Callable[[float, Callable], "threading.Timer"]] = None,
    ):
        self._repo = repo
        self._sos = sos_service
        self._timeout = verification_timeout
        # Indirection on Timer creation makes the engine testable without
        # actually waiting for real seconds to pass.
        self._timer_factory = timer_factory or (
            lambda secs, cb: threading.Timer(secs, cb)
        )
        self._pending: Dict[str, "threading.Timer"] = {}
        self._pending_reasons: Dict[str, BreachReason] = {}
        self._pending_deadlines: Dict[str, datetime] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------

    def process_record(self, record: HealthRecord) -> BreachReason:
        """Persist a record and trigger the verification flow if needed."""
        patient = self._repo.get_patient(record.patient_id)
        if patient is None:
            raise ValueError(f"Unknown patient: {record.patient_id}")

        self._repo.append_record(record)
        reason = evaluate_thresholds(record, patient.thresholds)

        if reason.any:
            self._on_breach(patient, record, reason)
        return reason

    def confirm_verification(self, patient_id: str) -> bool:
        """Patient confirmed they are OK — cancel the SOS timer."""
        with self._lock:
            timer = self._pending.pop(patient_id, None)
            self._pending_reasons.pop(patient_id, None)
            self._pending_deadlines.pop(patient_id, None)

        if timer is None:
            return False  # nothing pending

        timer.cancel()
        self._repo.append_event(
            Event(
                patient_id=patient_id,
                type=EventType.VERIFICATION_CONFIRMED,
                message="Patient confirmed they are OK; SOS cancelled.",
            )
        )
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _on_breach(
        self, patient: Patient, record: HealthRecord, reason: BreachReason
    ) -> None:
        # Audit the breach
        self._repo.append_event(
            Event(
                patient_id=patient.id,
                type=EventType.THRESHOLD_BREACH,
                message=f"Threshold breached: {reason.detail}",
                metadata={
                    "heart_rate": record.heart_rate,
                    "body_temperature": record.body_temperature,
                },
            )
        )

        with self._lock:
            # If a verification is already running for this patient, don't
            # stack another timer — keep the original one.
            if patient.id in self._pending:
                return

            # Send the verification prompt
            self._repo.append_event(
                Event(
                    patient_id=patient.id,
                    type=EventType.VERIFICATION_SENT,
                    message=(
                        f"Verification prompt sent — patient has {int(self._timeout)}s "
                        "to confirm they're OK."
                    ),
                )
            )

            timer = self._timer_factory(
                self._timeout, lambda: self._on_timeout(patient.id, reason)
            )
            self._pending[patient.id] = timer
            self._pending_reasons[patient.id] = reason
            self._pending_deadlines[patient.id] = (
                datetime.now(timezone.utc) + timedelta(seconds=self._timeout)
            )
            timer.daemon = True  # don't block process exit
            timer.start()

    def _on_timeout(self, patient_id: str, reason: BreachReason) -> None:
        """No verification arrived in time — escalate."""
        with self._lock:
            # Drop tracking before delegating
            self._pending.pop(patient_id, None)
            self._pending_reasons.pop(patient_id, None)
            self._pending_deadlines.pop(patient_id, None)

        # Re-fetch patient (state may have changed)
        patient = self._repo.get_patient(patient_id)
        if patient is None:
            return  # patient was deleted; nothing to do

        self._sos.initiate_emergency_protocol(patient, reason)

    # ------------------------------------------------------------------
    # Test / inspection helpers
    # ------------------------------------------------------------------

    def has_pending_verification(self, patient_id: str) -> bool:
        return patient_id in self._pending

    def pending_verification_deadline(self, patient_id: str) -> Optional[datetime]:
        return self._pending_deadlines.get(patient_id)

    def force_timeout(self, patient_id: str) -> None:
        """Test helper — fire the timeout immediately, bypassing the timer."""
        with self._lock:
            timer = self._pending.get(patient_id)
            reason = self._pending_reasons.get(patient_id)
        if timer is None or reason is None:
            raise RuntimeError(f"No pending verification for {patient_id}")
        timer.cancel()
        self._on_timeout(patient_id, reason)
