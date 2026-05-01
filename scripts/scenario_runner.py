"""Run repeatable VitalSense scenarios from the command line.

This is a lightweight development tool for exercising the core engine without
starting FastAPI. It uses the in-memory repository and a deterministic timer so
scenarios finish immediately.

Usage:
    python scripts/scenario_runner.py
    python scripts/scenario_runner.py normal confirm timeout fever
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import AnomalyDetectionEngine
from app.db.repository import InMemoryRepository
from app.models import (
    Doctor,
    EventType,
    FamilyMember,
    HealthRecord,
    Patient,
    PersonalizedThresholds,
)
from app.services import ConsoleNotifier, NotificationService, SOSService


class ManualTimer:
    """Timer double controlled by the scenario runner."""

    def __init__(self, secs: float, callback: Callable[[], None]):
        self.secs = secs
        self.callback = callback
        self.cancelled = False
        self.fired = False
        self.daemon = False

    def start(self) -> None:
        pass

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled and not self.fired:
            self.fired = True
            self.callback()


class ScenarioContext:
    def __init__(self) -> None:
        self.repo = InMemoryRepository()
        self.notifier = ConsoleNotifier()
        self.sos = SOSService(self.repo, NotificationService(self.notifier))
        self.timers: list[ManualTimer] = []
        self.engine = AnomalyDetectionEngine(
            self.repo,
            self.sos,
            verification_timeout=30.0,
            timer_factory=self._timer_factory,
        )
        self.patient = self._seed_patient()

    def _timer_factory(self, secs: float, callback: Callable[[], None]) -> ManualTimer:
        timer = ManualTimer(secs, callback)
        self.timers.append(timer)
        return timer

    def _seed_patient(self) -> Patient:
        doctor = self.repo.save_doctor(
            Doctor(
                name="Elif Demir",
                contact_number="+90-555-0100",
                specialty="Cardiology",
                on_call_status=True,
            )
        )
        patient = self.repo.save_patient(
            Patient(
                name="Ahmet Yilmaz",
                contact_number="+90-555-0200",
                location="Istanbul",
                age=67,
                height_cm=174,
                weight_kg=82,
                doctor_id=doctor.id,
                thresholds=PersonalizedThresholds(
                    heart_rate_min=55,
                    heart_rate_max=120,
                    temperature_min=35.8,
                    temperature_max=38.4,
                ),
            )
        )
        self.repo.save_family_member(
            FamilyMember(
                name="Mina Yilmaz",
                contact_number="+90-555-0300",
                relationship="daughter",
                patient_id=patient.id,
            )
        )
        return patient

    def push(self, heart_rate: int, temperature: float, steps: int = 0) -> None:
        self.engine.process_record(
            HealthRecord(
                patient_id=self.patient.id,
                heart_rate=heart_rate,
                body_temperature=temperature,
                daily_steps=steps,
            )
        )

    def fire_latest_timer(self) -> None:
        if not self.timers:
            raise RuntimeError("No timer was created")
        self.timers[-1].fire()


def run_normal(ctx: ScenarioContext) -> None:
    ctx.push(78, 36.7, 1400)


def run_confirm(ctx: ScenarioContext) -> None:
    ctx.push(132, 36.9, 1520)
    ctx.engine.confirm_verification(ctx.patient.id)


def run_timeout(ctx: ScenarioContext) -> None:
    ctx.push(134, 37.1, 1600)
    ctx.fire_latest_timer()


def run_fever(ctx: ScenarioContext) -> None:
    ctx.push(92, 39.3, 900)
    ctx.fire_latest_timer()


SCENARIOS: dict[str, Callable[[ScenarioContext], None]] = {
    "normal": run_normal,
    "confirm": run_confirm,
    "timeout": run_timeout,
    "fever": run_fever,
}


def print_summary(name: str, ctx: ScenarioContext) -> None:
    events = list(reversed(ctx.repo.recent_events(ctx.patient.id)))
    latest = ctx.repo.recent_records(ctx.patient.id, limit=1)[0]
    print(f"\n{name}")
    print("-" * len(name))
    print(f"latest: HR={latest.heart_rate} bpm, Temp={latest.body_temperature} C")
    print(f"pending verification: {ctx.engine.has_pending_verification(ctx.patient.id)}")
    print(f"notifications sent: {len(ctx.notifier.sent)}")
    if not events:
        print("events: none")
        return
    print("events:")
    for event in events:
        marker = "!" if event.type in {
            EventType.THRESHOLD_BREACH,
            EventType.SOS_TRIGGERED,
        } else "-"
        print(f"  {marker} {event.type.value}: {event.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run VitalSense engine scenarios")
    parser.add_argument(
        "scenarios",
        nargs="*",
        choices=sorted(SCENARIOS),
        default=list(SCENARIOS),
        help="Scenario names to run",
    )
    args = parser.parse_args()

    for name in args.scenarios:
        ctx = ScenarioContext()
        SCENARIOS[name](ctx)
        print_summary(name, ctx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
