"""Simulated BLE watch adapter.

The SimulatedBLEWatch emits a raw JSON payload (mimicking what a custom
firmware over BLE might send). The adapter parses it into the standard form.
"""
from __future__ import annotations

import json
import random
from typing import Optional

from .base import StandardWearable


class SimulatedBLEWatch:
    """Emits a JSON-encoded packet, like raw BLE characteristic data."""

    def __init__(
        self,
        heart: int = 75,
        temp: float = 36.7,
        steps: int = 0,
        jitter: float = 0.0,
    ):
        self._heart = heart
        self._temp = temp
        self._steps = steps
        self._jitter = jitter

    def fetch_raw_sensor_data(self) -> str:
        # Add small random jitter to feel like real telemetry
        h = self._heart + (random.randint(-2, 2) if self._jitter else 0)
        t = self._temp + (random.uniform(-0.1, 0.1) * self._jitter)
        return json.dumps({"hr_bpm": h, "temp_c": round(t, 2), "steps": self._steps})

    def set_state(
        self,
        heart: Optional[int] = None,
        temp: Optional[float] = None,
        steps: Optional[int] = None,
    ) -> None:
        if heart is not None:
            self._heart = heart
        if temp is not None:
            self._temp = temp
        if steps is not None:
            self._steps = steps


class SimulatedWatchAdapter(StandardWearable):
    def __init__(self, watch: SimulatedBLEWatch):
        self._watch = watch
        self._cache: dict = {}

    def _refresh(self) -> dict:
        self._cache = json.loads(self._watch.fetch_raw_sensor_data())
        return self._cache

    def get_heart_rate(self) -> int:
        return int(self._refresh()["hr_bpm"])

    def get_temperature(self) -> float:
        return float(self._refresh()["temp_c"])

    def get_steps(self) -> int:
        return int(self._refresh().get("steps", 0))
