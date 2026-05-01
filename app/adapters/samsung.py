"""Samsung Health adapter."""
from __future__ import annotations

from .base import StandardWearable


class SamsungHealthAPI:
    """Stand-in for Samsung Health SDK."""

    def __init__(self, heart: int = 70, temp: float = 36.5, steps: int = 0):
        self._heart = heart
        self._temp = temp
        self._steps = steps

    def read_heart_sensor(self) -> int:
        return self._heart

    def read_temperature_sensor(self) -> float:
        return self._temp

    def get_step_data(self) -> int:
        return self._steps

    def set_heart(self, value: int) -> None:
        self._heart = value

    def set_temp(self, value: float) -> None:
        self._temp = value


class SamsungWatchAdapter(StandardWearable):
    def __init__(self, api: SamsungHealthAPI):
        self._api = api

    def get_heart_rate(self) -> int:
        return self._api.read_heart_sensor()

    def get_temperature(self) -> float:
        return self._api.read_temperature_sensor()

    def get_steps(self) -> int:
        return self._api.get_step_data()
