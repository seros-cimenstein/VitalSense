"""Apple Health adapter.

The (mock) AppleHealthAPI uses fetch_pulse() and read_body_temp() — names
incompatible with our standard interface. AppleHealthAdapter bridges the gap.
"""
from __future__ import annotations

from .base import StandardWearable


class AppleHealthAPI:
    """Stand-in for the real Apple HealthKit SDK."""

    def __init__(self, pulse: int = 72, body_temp: float = 36.6, steps: int = 0):
        self._pulse = pulse
        self._body_temp = body_temp
        self._steps = steps

    def fetch_pulse(self) -> int:
        return self._pulse

    def read_body_temp(self) -> float:
        return self._body_temp

    def step_count(self) -> int:
        return self._steps

    # helpers used by the demo / tests to drive the device
    def set_pulse(self, value: int) -> None:
        self._pulse = value

    def set_body_temp(self, value: float) -> None:
        self._body_temp = value


class AppleHealthAdapter(StandardWearable):
    def __init__(self, api: AppleHealthAPI):
        self._api = api

    def get_heart_rate(self) -> int:
        return self._api.fetch_pulse()

    def get_temperature(self) -> float:
        return self._api.read_body_temp()

    def get_steps(self) -> int:
        return self._api.step_count()
