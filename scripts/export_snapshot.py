"""Export a demo doctor handoff snapshot as JSON.

The script runs one deterministic scenario, collects the patient snapshot,
events, contacts, and notification attempts, then writes a JSON payload. It is
useful for demos, debugging API consumers, or capturing sample data for docs.

Usage:
    python scripts/export_snapshot.py timeout
    python scripts/export_snapshot.py fever --output /tmp/fever-snapshot.json
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.scenario_runner import SCENARIOS, ScenarioContext


def build_payload(scenario: str) -> dict[str, Any]:
    ctx = ScenarioContext()
    # ConsoleNotifier prints delivery attempts. Suppress that so stdout stays
    # valid JSON when --output is not used.
    with contextlib.redirect_stdout(io.StringIO()):
        SCENARIOS[scenario](ctx)

    snapshot = ctx.sos.fetch_snapshot(ctx.patient.id)
    events = list(reversed(ctx.repo.recent_events(ctx.patient.id)))
    doctors = ctx.repo.list_doctors()
    family = ctx.repo.list_family_for_patient(ctx.patient.id)

    return {
        "scenario": scenario,
        "patient": ctx.patient.model_dump(mode="json"),
        "doctor": doctors[0].model_dump(mode="json") if doctors else None,
        "family": [member.model_dump(mode="json") for member in family],
        "snapshot": snapshot.model_dump(mode="json") if snapshot else None,
        "events": [event.model_dump(mode="json") for event in events],
        "notifications": [
            {"recipient": recipient, "message": message}
            for recipient, message in ctx.notifier.sent
        ],
        "pending_verification": ctx.engine.has_pending_verification(ctx.patient.id),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a VitalSense demo snapshot")
    parser.add_argument("scenario", choices=sorted(SCENARIOS), help="Scenario to run")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Write JSON to this path instead of stdout",
    )
    args = parser.parse_args()

    payload = build_payload(args.scenario)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
