"""Health chat service.

The service owns persistence and timeline logging. Response generation is
delegated to a small model provider, either the baked-in local triage model or
an external API-backed model configured through environment variables.
"""
from __future__ import annotations

from typing import Optional

from app.db import Repository
from app.models import (
    ChatMessage,
    ChatResult,
    ChatRole,
    ChatUrgency,
    Event,
    EventType,
    Patient,
)
from app.services.health_chat_model import HealthChatModel, LocalTriageHealthChatModel


class HealthChatService:
    def __init__(
        self,
        repo: Repository,
        model: Optional[HealthChatModel] = None,
    ) -> None:
        self._repo = repo
        self._model = model or LocalTriageHealthChatModel()

    def respond(
        self,
        patient: Patient,
        message: str,
        include_snapshot: bool = True,
    ) -> ChatResult:
        cleaned = _clean_message(message)
        if not cleaned:
            raise ValueError("message is required")

        latest_record = self._repo.recent_records(patient.id, limit=1)[0:1]
        latest = latest_record[0] if include_snapshot and latest_record else None
        decision = self._model.generate(patient, cleaned, latest)

        patient_message = self._repo.append_chat_message(
            ChatMessage(
                patient_id=patient.id,
                role=ChatRole.PATIENT,
                content=cleaned,
                urgency=decision.urgency,
                metadata={"include_snapshot": include_snapshot},
            )
        )
        assistant_message = self._repo.append_chat_message(
            ChatMessage(
                patient_id=patient.id,
                role=ChatRole.ASSISTANT,
                content=decision.reply,
                urgency=decision.urgency,
                metadata={
                    "recommended_action": decision.recommended_action.value,
                    "doctor_summary": decision.doctor_summary,
                    "patient_message_id": patient_message.id,
                    "matched_signals": decision.signals,
                    "latest_record_id": latest.id if latest else None,
                    "model_provider": decision.provider,
                    "model_name": decision.model_name,
                    "model_confidence": decision.confidence,
                },
            )
        )

        event_logged = False
        if decision.urgency in {ChatUrgency.URGENT, ChatUrgency.EMERGENCY}:
            self._repo.append_event(
                Event(
                    patient_id=patient.id,
                    type=EventType.CHAT_TRIAGE,
                    message=f"Chat triage classified as {decision.urgency.value}.",
                    metadata={
                        "urgency": decision.urgency.value,
                        "recommended_action": decision.recommended_action.value,
                        "assistant_message_id": assistant_message.id,
                        "model_provider": decision.provider,
                        "model_name": decision.model_name,
                    },
                )
            )
            event_logged = True

        return ChatResult(
            reply=decision.reply,
            urgency=decision.urgency,
            recommended_action=decision.recommended_action,
            doctor_summary=decision.doctor_summary,
            event_logged=event_logged,
        )

    def share_latest_summary(self, patient: Patient, shared_by: str) -> Optional[str]:
        for message in self._repo.recent_chat_messages(patient.id, limit=20):
            if message.role != ChatRole.ASSISTANT:
                continue
            summary = message.metadata.get("doctor_summary")
            if not summary:
                continue
            self._repo.append_event(
                Event(
                    patient_id=patient.id,
                    type=EventType.CHAT_TRIAGE,
                    message=f"Chat summary shared with doctor by {shared_by}.",
                    metadata={
                        "doctor_id": patient.doctor_id,
                        "assistant_message_id": message.id,
                        "urgency": message.urgency.value,
                        "doctor_summary": summary,
                        "model_provider": message.metadata.get("model_provider"),
                        "model_name": message.metadata.get("model_name"),
                    },
                )
            )
            return str(summary)
        return None


def _clean_message(message: str) -> str:
    return " ".join(message.strip().split())
