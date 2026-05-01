"""SOSService — the emergency event consumer.

When the AnomalyDetectionEngine times out waiting for verification, it calls
initiate_emergency_protocol, which:
  1. Notifies every registered family member (SMS).
  2. Builds a HealthSnapshot and notifies the on-call doctor with a link.
  3. Records every step as an Event (audit trail).
"""
from __future__ import annotations

from typing import Optional

from app.db import Repository
from app.models import (
    Event,
    EventType,
    HealthSnapshot,
    Patient,
)
from app.services.notification_service import NotificationService


class SOSService:
    def __init__(
        self,
        repo: Repository,
        notification_service: NotificationService,
        snapshot_base_url: str = "https://vitalsense.example/snapshot",
    ):
        self._repo = repo
        self._notify = notification_service
        self._snapshot_base_url = snapshot_base_url

    def initiate_emergency_protocol(self, patient: Patient, reason) -> HealthSnapshot:
        """Run the full SOS flow. Returns the snapshot that was shared."""
        self._repo.append_event(
            Event(
                patient_id=patient.id,
                type=EventType.SOS_TRIGGERED,
                message=f"SOS triggered: {reason.detail}",
            )
        )

        # Call the patient first
        call_sent = self._notify.send_call_to_patient(patient.contact_number, patient.name)
        self._repo.append_event(
            Event(
                patient_id=patient.id,
                type=EventType.CALL_ATTEMPTED,
                message=f"Automated call placed to {patient.name} ({patient.contact_number}).",
                metadata={"delivered": call_sent, "contact": patient.contact_number},
            )
        )

        snapshot = self._build_snapshot(patient, reason)
        self._notify_family(patient, reason)
        self._notify_doctor(patient, snapshot)
        return snapshot

    # ------------------------------------------------------------------

    def _build_snapshot(self, patient: Patient, reason) -> HealthSnapshot:
        records = self._repo.recent_records(patient.id, limit=20)
        return HealthSnapshot(
            patient=patient,
            recent_records=records,
            reason=reason.detail,
        )

    def _notify_family(self, patient: Patient, reason) -> None:
        family = self._repo.list_family_for_patient(patient.id)
        for member in family:
            delivered = self._notify.send_family_sms(
                contact=member.contact_number,
                patient_name=patient.name,
                detail=reason.detail,
                location=patient.location,
            )
            self._repo.append_event(
                Event(
                    patient_id=patient.id,
                    type=EventType.FAMILY_NOTIFIED,
                    message=f"SMS sent to {member.relationship} ({member.name}).",
                    metadata={
                        "family_member_id": member.id,
                        "delivered": delivered,
                        "contact": member.contact_number,
                    },
                )
            )

    def _notify_doctor(self, patient: Patient, snapshot: HealthSnapshot) -> None:
        if patient.doctor_id is None:
            return
        doctor = self._repo.get_doctor(patient.doctor_id)
        if doctor is None or not doctor.on_call_status:
            return

        snapshot_url = f"{self._snapshot_base_url}/{patient.id}"
        delivered = self._notify.send_doctor_alert(
            contact=doctor.contact_number,
            patient_name=patient.name,
            snapshot_url=snapshot_url,
        )
        self._repo.append_event(
            Event(
                patient_id=patient.id,
                type=EventType.DOCTOR_NOTIFIED,
                message=f"Snapshot link shared with Dr. {doctor.name} ({doctor.specialty}).",
                metadata={
                    "doctor_id": doctor.id,
                    "snapshot_url": snapshot_url,
                    "delivered": delivered,
                    "contact": doctor.contact_number,
                },
            )
        )

    # ------------------------------------------------------------------

    def fetch_snapshot(self, patient_id: str) -> Optional[HealthSnapshot]:
        """Doctor-facing: assemble a fresh snapshot on demand."""
        patient = self._repo.get_patient(patient_id)
        if patient is None:
            return None
        records = self._repo.recent_records(patient_id, limit=20)
        latest = records[0] if records else None
        reason_detail = (
            f"Most recent: HR={latest.heart_rate}, Temp={latest.body_temperature}"
            if latest
            else "no recent telemetry"
        )
        return HealthSnapshot(
            patient=patient,
            recent_records=records,
            reason=reason_detail,
        )
