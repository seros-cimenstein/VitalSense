"""Generate a burst of telemetry through the VitalSense core engine.

This is a development utility for quick throughput and behavior checks. It
does not start FastAPI or touch external services.

Usage:
    python scripts/load_simulation.py
    python scripts/load_simulation.py --readings 1000 --spike-every 25
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import EventType
from scripts.scenario_runner import ScenarioContext


def reading_at(index: int, spike_every: int) -> tuple[int, float, int]:
    """Return deterministic telemetry for the given sample index."""
    if spike_every > 0 and index > 0 and index % spike_every == 0:
        return 132 + (index % 9), 37.3, index * 11
    heart_rate = 74 + (index % 18)
    temperature = 36.4 + ((index % 7) * 0.1)
    return heart_rate, round(temperature, 1), index * 11


def run_load(readings: int, spike_every: int, auto_timeout: bool) -> dict[str, float | int]:
    ctx = ScenarioContext()
    started = time.perf_counter()
    for index in range(readings):
        heart_rate, temperature, steps = reading_at(index, spike_every)
        with contextlib.redirect_stdout(io.StringIO()):
            ctx.push(heart_rate, temperature, steps)
            if auto_timeout and ctx.engine.has_pending_verification(ctx.patient.id):
                ctx.fire_latest_timer()

    elapsed = time.perf_counter() - started
    events = ctx.repo.recent_events(ctx.patient.id, limit=max(readings * 4, 50))
    return {
        "readings": readings,
        "elapsed_seconds": round(elapsed, 4),
        "readings_per_second": round(readings / elapsed, 2) if elapsed else readings,
        "records_stored": len(ctx.repo.recent_records(ctx.patient.id, limit=readings)),
        "events": len(events),
        "threshold_breaches": sum(1 for event in events if event.type == EventType.THRESHOLD_BREACH),
        "sos_triggered": sum(1 for event in events if event.type == EventType.SOS_TRIGGERED),
        "notifications": len(ctx.notifier.sent),
        "pending_verification": int(ctx.engine.has_pending_verification(ctx.patient.id)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a VitalSense telemetry load simulation")
    parser.add_argument("--readings", type=int, default=250, help="Number of readings to push")
    parser.add_argument(
        "--spike-every",
        type=int,
        default=40,
        help="Create an out-of-range heart-rate sample every N readings; 0 disables spikes",
    )
    parser.add_argument(
        "--no-timeout",
        action="store_true",
        help="Leave the first verification pending instead of forcing SOS after each spike",
    )
    args = parser.parse_args()

    if args.readings < 1:
        parser.error("--readings must be at least 1")
    if args.spike_every < 0:
        parser.error("--spike-every cannot be negative")

    summary = run_load(args.readings, args.spike_every, auto_timeout=not args.no_timeout)
    width = max(len(key) for key in summary)
    for key, value in summary.items():
        print(f"{key:{width}} : {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
