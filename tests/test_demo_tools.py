"""Tests for the standalone demo/development scripts."""
from __future__ import annotations

from scripts.export_snapshot import build_payload
from scripts.load_simulation import reading_at, run_load


def test_export_snapshot_timeout_payload_contains_handoff_data():
    payload = build_payload("timeout")

    assert payload["scenario"] == "timeout"
    assert payload["patient"]["name"] == "Ahmet Yilmaz"
    assert payload["doctor"]["specialty"] == "Cardiology"
    assert len(payload["family"]) == 1
    assert payload["snapshot"]["recent_records"]
    assert payload["pending_verification"] is False

    event_types = [event["type"] for event in payload["events"]]
    assert "threshold_breach" in event_types
    assert "sos_triggered" in event_types
    assert "doctor_notified" in event_types
    assert len(payload["notifications"]) == 3


def test_export_snapshot_confirm_payload_has_no_notifications():
    payload = build_payload("confirm")

    assert payload["pending_verification"] is False
    assert payload["notifications"] == []
    event_types = [event["type"] for event in payload["events"]]
    assert event_types == [
        "threshold_breach",
        "verification_sent",
        "verification_confirmed",
    ]


def test_load_simulation_counts_spikes_and_timeouts():
    summary = run_load(readings=81, spike_every=20, auto_timeout=True)

    assert summary["readings"] == 81
    assert summary["records_stored"] == 81
    assert summary["threshold_breaches"] == 4
    assert summary["sos_triggered"] == 4
    assert summary["notifications"] == 12
    assert summary["pending_verification"] == 0
    assert summary["readings_per_second"] > 0


def test_load_simulation_can_leave_verification_pending():
    summary = run_load(readings=81, spike_every=20, auto_timeout=False)

    assert summary["threshold_breaches"] == 4
    assert summary["sos_triggered"] == 0
    assert summary["notifications"] == 0
    assert summary["pending_verification"] == 1


def test_reading_at_is_deterministic():
    assert reading_at(0, spike_every=20) == (74, 36.4, 0)
    assert reading_at(20, spike_every=20) == (134, 37.3, 220)
    assert reading_at(20, spike_every=0) == (76, 37.0, 220)
