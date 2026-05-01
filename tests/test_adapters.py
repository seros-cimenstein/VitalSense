"""Adapter tests — every adapter conforms to StandardWearable identically."""
from __future__ import annotations

import pytest

from app.adapters import (
    AppleHealthAPI,
    AppleHealthAdapter,
    SamsungHealthAPI,
    SamsungWatchAdapter,
    SimulatedBLEWatch,
    SimulatedWatchAdapter,
    StandardWearable,
)


def test_apple_adapter_translates_method_names():
    api = AppleHealthAPI(pulse=82, body_temp=36.9, steps=4200)
    adapter = AppleHealthAdapter(api)
    assert isinstance(adapter, StandardWearable)
    assert adapter.get_heart_rate() == 82
    assert adapter.get_temperature() == 36.9
    assert adapter.get_steps() == 4200


def test_samsung_adapter_translates_method_names():
    api = SamsungHealthAPI(heart=68, temp=36.4, steps=1100)
    adapter = SamsungWatchAdapter(api)
    assert isinstance(adapter, StandardWearable)
    assert adapter.get_heart_rate() == 68
    assert adapter.get_temperature() == 36.4
    assert adapter.get_steps() == 1100


def test_simulated_adapter_parses_raw_json():
    watch = SimulatedBLEWatch(heart=95, temp=37.1, steps=300)
    adapter = SimulatedWatchAdapter(watch)
    assert isinstance(adapter, StandardWearable)
    assert adapter.get_heart_rate() == 95
    assert adapter.get_temperature() == 37.1
    assert adapter.get_steps() == 300


def test_adapters_are_polymorphic():
    """The Anomaly Engine never has to know which vendor it is talking to."""
    devices: list[StandardWearable] = [
        AppleHealthAdapter(AppleHealthAPI(pulse=70, body_temp=36.5)),
        SamsungWatchAdapter(SamsungHealthAPI(heart=72, temp=36.6)),
        SimulatedWatchAdapter(SimulatedBLEWatch(heart=74, temp=36.7)),
    ]
    rates = [d.get_heart_rate() for d in devices]
    temps = [d.get_temperature() for d in devices]
    assert rates == [70, 72, 74]
    # SimulatedBLEWatch has 0.0 jitter by default — exact match
    assert temps == [36.5, 36.6, 36.7]


def test_cannot_instantiate_standard_wearable_directly():
    with pytest.raises(TypeError):
        StandardWearable()  # type: ignore[abstract]
