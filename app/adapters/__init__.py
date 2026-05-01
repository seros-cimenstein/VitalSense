"""Wearable adapters package.

The Adapter pattern lets VitalSense work with any smartwatch SDK without
touching the core anomaly engine. Each vendor SDK has its own incompatible
method names; an adapter wraps it and exposes the StandardWearable interface.
"""
from .base import StandardWearable
from .apple import AppleHealthAPI, AppleHealthAdapter
from .samsung import SamsungHealthAPI, SamsungWatchAdapter
from .simulated import SimulatedBLEWatch, SimulatedWatchAdapter

__all__ = [
    "StandardWearable",
    "AppleHealthAPI",
    "AppleHealthAdapter",
    "SamsungHealthAPI",
    "SamsungWatchAdapter",
    "SimulatedBLEWatch",
    "SimulatedWatchAdapter",
]
