"""End-to-end VitalSense demo: Ahmet's scenario from the progress report.

Walks through:
  1. Register Ahmet (elderly patient), his son, and his doctor.
  2. Set personalized thresholds.
  3. Simulate normal telemetry from a SimulatedBLEWatch — nothing happens.
  4. Spike the heart rate to 130 BPM — engine sends a verification prompt.
  5. Ahmet doesn't respond — the timer fires, SOS is triggered.
  6. Family is SMS'd, doctor receives a snapshot link, audit trail is printed.

Run from the project root:
    python scripts/demo.py
"""
from __future__ import annotations

import sys
import time
import os
from pathlib import Path

# allow running this script directly: ``python scripts/demo.py``
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters import SimulatedBLEWatch, SimulatedWatchAdapter
from app.core import AnomalyDetectionEngine
from app.db import get_repository
from app.db.repository import reset_repository
from app.models import (
    Doctor,
    FamilyMember,
    HealthRecord,
    Patient,
    PersonalizedThresholds,
)
from app.services import ConsoleNotifier, NotificationService, SOSService


def banner(text: str) -> None:
    line = "─" * 72
    print(f"\n{line}\n  {text}\n{line}")


def print_events(repo, patient_id: str) -> None:
    events = list(reversed(repo.recent_events(patient_id)))
    for e in events:
        ts = e.timestamp.strftime("%H:%M:%S")
        print(f"  [{ts}] {e.type.value:>22} · {e.message}")


def main() -> int:
    os.environ["VITALSENSE_REPOSITORY"] = "memory"
    reset_repository()  # ensure a clean in-memory store
    repo = get_repository()

    notifier = ConsoleNotifier()
    notif = NotificationService(notifier)
    sos = SOSService(repo, notif)
    # Use a 2-second verification window so the demo runs quickly.
    engine = AnomalyDetectionEngine(repo, sos, verification_timeout=2.0)

    # ------------------------------------------------------------------
    banner("1. Setting up Ahmet, his son, and his on-call doctor")
    # ------------------------------------------------------------------
    doctor = repo.save_doctor(
        Doctor(
            name="Dr. Aylin Demir",
            contact_number="+90-555-0100",
            specialty="Cardiology",
            on_call_status=True,
        )
    )
    ahmet = repo.save_patient(
        Patient(
            name="Ahmet Yılmaz",
            contact_number="+90-555-0200",
            location="İzmir, Karşıyaka",
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
    son = repo.save_family_member(
        FamilyMember(
            name="Mehmet Yılmaz",
            contact_number="+90-555-0300",
            relationship="son",
            patient_id=ahmet.id,
        )
    )
    print(f"  patient   : {ahmet.name} (BMI {ahmet.bmi})")
    print(f"  doctor    : Dr. {doctor.name}, {doctor.specialty} · on-call={doctor.on_call_status}")
    print(f"  family    : {son.name} ({son.relationship})")
    print(f"  thresholds: HR {ahmet.thresholds.heart_rate_min}-{ahmet.thresholds.heart_rate_max} bpm, "
          f"Temp {ahmet.thresholds.temperature_min}-{ahmet.thresholds.temperature_max} °C")

    # ------------------------------------------------------------------
    banner("2. Wearable adapter — SimulatedBLEWatch behind StandardWearable")
    # ------------------------------------------------------------------
    watch = SimulatedBLEWatch(heart=78, temp=36.7)
    wearable = SimulatedWatchAdapter(watch)
    print(f"  device   : {wearable.device_name}")
    print(f"  reading  : HR={wearable.get_heart_rate()} bpm, Temp={wearable.get_temperature()} °C")

    def push() -> None:
        record = HealthRecord(
            patient_id=ahmet.id,
            heart_rate=wearable.get_heart_rate(),
            body_temperature=wearable.get_temperature(),
            daily_steps=wearable.get_steps(),
        )
        engine.process_record(record)

    # ------------------------------------------------------------------
    banner("3. Normal telemetry — nothing should happen")
    # ------------------------------------------------------------------
    push()
    print(f"  pending verification? {engine.has_pending_verification(ahmet.id)}")

    # ------------------------------------------------------------------
    banner("4. Heart rate spikes to 130 BPM (Ahmet feels dizzy)")
    # ------------------------------------------------------------------
    watch.set_state(heart=130)
    push()
    print(f"  pending verification? {engine.has_pending_verification(ahmet.id)}")
    print("  → engine sent a verification prompt; waiting 2s for Ahmet to respond...")

    # ------------------------------------------------------------------
    banner("5. Ahmet doesn't respond — timer fires, SOS protocol runs")
    # ------------------------------------------------------------------
    time.sleep(2.5)  # let the timer fire
    print(f"  pending verification? {engine.has_pending_verification(ahmet.id)}")

    # ------------------------------------------------------------------
    banner("6. Audit trail")
    # ------------------------------------------------------------------
    print_events(repo, ahmet.id)

    # ------------------------------------------------------------------
    banner("7. Doctor pulls a fresh snapshot")
    # ------------------------------------------------------------------
    snap = sos.fetch_snapshot(ahmet.id)
    if snap:
        print(f"  patient        : {snap.patient.name}")
        print(f"  recent records : {len(snap.recent_records)}")
        print(f"  triggered_at   : {snap.triggered_at.isoformat()}")
        print(f"  reason         : {snap.reason}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
