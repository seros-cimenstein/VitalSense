"""StandardWearable: the target interface every adapter conforms to."""
from __future__ import annotations

from abc import ABC, abstractmethod


class StandardWearable(ABC):
    """Unified contract the Anomaly Detection Engine depends on.

    Concrete adapters translate vendor-specific calls (fetch_pulse,
    read_heart_sensor, fetch_raw_sensor_data, ...) into these methods.
    """

    @abstractmethod
    def get_heart_rate(self) -> int:
        """Return current heart rate in BPM."""

    @abstractmethod
    def get_temperature(self) -> float:
        """Return current body temperature in degrees Celsius."""

    def get_steps(self) -> int:
        """Optional: return today's step count. Defaults to 0."""
        return 0

    @property
    def device_name(self) -> str:
        return self.__class__.__name__
