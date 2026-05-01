"""Notification service.

Defines a Notifier protocol (so SMS gateway, email, push, etc. can be swapped
in) and a ConsoleNotifier that prints to stdout — handy for local runs and
tests, and what the demo uses.
"""
from __future__ import annotations

from typing import List, Protocol


class Notifier(Protocol):
    """Anything that can deliver a message to a recipient."""

    def send(self, recipient_contact: str, message: str) -> bool: ...


class ConsoleNotifier:
    """Simple notifier that prints. Records every send for inspection."""

    def __init__(self) -> None:
        self.sent: List[tuple[str, str]] = []

    def send(self, recipient_contact: str, message: str) -> bool:
        self.sent.append((recipient_contact, message))
        print(f"[notify -> {recipient_contact}] {message}")
        return True


class NotificationService:
    """Wraps a Notifier with structured methods for each alert kind."""

    def __init__(self, notifier: Notifier):
        self._notifier = notifier

    def send_family_sms(self, contact: str, patient_name: str, detail: str, location: str | None) -> bool:
        loc = f" Location: {location}." if location else ""
        msg = (
            f"VitalSense ALERT — {patient_name} may need help. "
            f"Reason: {detail}.{loc}"
        )
        return self._notifier.send(contact, msg)

    def send_doctor_alert(self, contact: str, patient_name: str, snapshot_url: str) -> bool:
        msg = (
            f"VitalSense URGENT — patient {patient_name} flagged. "
            f"Snapshot: {snapshot_url}"
        )
        return self._notifier.send(contact, msg)
