"""Rule-based health chat service.

The service is intentionally vendor-neutral. It stores patient/assistant turns,
uses recent telemetry as context, and applies conservative triage rules when no
LLM provider is configured.
"""
from __future__ import annotations

import re
from typing import Optional

from app.db import Repository
from app.models import (
    ChatMessage,
    ChatRecommendedAction,
    ChatResult,
    ChatRole,
    ChatUrgency,
    Event,
    EventType,
    HealthRecord,
    Patient,
)


EMERGENCY_PHRASES = (
    "chest pain",
    "chest pressure",
    "chest tight",
    "tight chest",
    "heart attack",
    "can't breathe",
    "cannot breathe",
    "severe shortness of breath",
    "fainted",
    "fainting",
    "passed out",
    "loss of consciousness",
    "face drooping",
    "arm weakness",
    "speech trouble",
    "slurred speech",
    "stroke",
    "severe allergic",
    "anaphylaxis",
    "suicidal",
    "self harm",
    "self-harm",
    "kill myself",
)

URGENT_PHRASES = (
    "short of breath",
    "short breath",
    "breathless",
    "dizzy",
    "dizziness",
    "palpitations",
    "heart racing",
    "high fever",
    "fever",
    "severe pain",
    "vomiting",
    "weakness",
)

WATCH_PHRASES = (
    "tired",
    "fatigue",
    "headache",
    "nausea",
    "cough",
    "sore throat",
    "sweating",
    "unwell",
)

OK_PHRASES = (
    "i'm okay",
    "i am okay",
    "im okay",
    "i'm ok",
    "i am ok",
    "all good",
    "feel fine",
)


class HealthChatService:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo

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
        urgency, action, signals = self._classify(patient, cleaned, latest)
        vitals_context = _vitals_context(patient, latest)

        reply = self._build_reply(cleaned, urgency, action, signals, vitals_context)
        doctor_summary = self._build_doctor_summary(
            patient=patient,
            patient_message=cleaned,
            urgency=urgency,
            action=action,
            vitals_context=vitals_context,
        )

        patient_message = self._repo.append_chat_message(
            ChatMessage(
                patient_id=patient.id,
                role=ChatRole.PATIENT,
                content=cleaned,
                urgency=urgency,
                metadata={"include_snapshot": include_snapshot},
            )
        )
        assistant_message = self._repo.append_chat_message(
            ChatMessage(
                patient_id=patient.id,
                role=ChatRole.ASSISTANT,
                content=reply,
                urgency=urgency,
                metadata={
                    "recommended_action": action.value,
                    "doctor_summary": doctor_summary,
                    "patient_message_id": patient_message.id,
                    "matched_signals": signals,
                    "latest_record_id": latest.id if latest else None,
                },
            )
        )

        event_logged = False
        if urgency in {ChatUrgency.URGENT, ChatUrgency.EMERGENCY}:
            self._repo.append_event(
                Event(
                    patient_id=patient.id,
                    type=EventType.CHAT_TRIAGE,
                    message=f"Chat triage classified as {urgency.value}.",
                    metadata={
                        "urgency": urgency.value,
                        "recommended_action": action.value,
                        "assistant_message_id": assistant_message.id,
                    },
                )
            )
            event_logged = True

        return ChatResult(
            reply=reply,
            urgency=urgency,
            recommended_action=action,
            doctor_summary=doctor_summary,
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
                    },
                )
            )
            return str(summary)
        return None

    def _classify(
        self,
        patient: Patient,
        message: str,
        latest: Optional[HealthRecord],
    ) -> tuple[ChatUrgency, ChatRecommendedAction, list[str]]:
        normalized = _normalize(message)
        emergency_hits = _phrase_hits(normalized, EMERGENCY_PHRASES)
        urgent_hits = _phrase_hits(normalized, URGENT_PHRASES)
        watch_hits = _phrase_hits(normalized, WATCH_PHRASES)
        ok_hits = _phrase_hits(normalized, OK_PHRASES)
        vital_flags, vital_severity = _vital_flags(patient, latest)

        signals = emergency_hits + urgent_hits + watch_hits + vital_flags

        if "confusion" in normalized or "confused" in normalized:
            if vital_severity == ChatUrgency.URGENT:
                return (
                    ChatUrgency.EMERGENCY,
                    ChatRecommendedAction.TRIGGER_SOS,
                    signals + ["confusion with abnormal vitals"],
                )
            urgent_hits.append("confusion")
            signals.append("confusion")

        if emergency_hits:
            return (
                ChatUrgency.EMERGENCY,
                ChatRecommendedAction.TRIGGER_SOS,
                signals,
            )

        if urgent_hits or vital_severity == ChatUrgency.URGENT:
            return (
                ChatUrgency.URGENT,
                ChatRecommendedAction.SHARE_DOCTOR,
                signals,
            )

        if watch_hits or vital_severity == ChatUrgency.WATCH:
            return (
                ChatUrgency.WATCH,
                ChatRecommendedAction.VERIFY,
                signals,
            )

        if ok_hits and vital_flags:
            return (
                ChatUrgency.WATCH,
                ChatRecommendedAction.VERIFY,
                signals,
            )

        return (
            ChatUrgency.ROUTINE,
            ChatRecommendedAction.NONE,
            signals or ["no red flags detected"],
        )

    def _build_reply(
        self,
        patient_message: str,
        urgency: ChatUrgency,
        action: ChatRecommendedAction,
        signals: list[str],
        vitals_context: str,
    ) -> str:
        disclaimer = "I am not a doctor and cannot diagnose."
        if urgency == ChatUrgency.EMERGENCY:
            return (
                "This may be urgent. Please call emergency services now or ask someone "
                "nearby to help. "
                f"{disclaimer} VitalSense can alert your family and doctor now."
            )
        if urgency == ChatUrgency.URGENT:
            primary_signal = signals[0] if signals else "your symptoms"
            return (
                f"{disclaimer} Because you mentioned {primary_signal}, please contact your "
                f"doctor or urgent care today. {vitals_context} I can share a concise "
                "summary with your doctor."
            )
        if urgency == ChatUrgency.WATCH:
            return (
                f"{disclaimer} {vitals_context} Keep monitoring your symptoms, and seek "
                "urgent help if you develop chest pain, severe shortness of breath, "
                "fainting, or stroke-like symptoms. Did this start suddenly or is it "
                "getting worse?"
            )
        if action == ChatRecommendedAction.NONE and len(patient_message) < 8:
            return (
                f"{disclaimer} {vitals_context} Tell me what you are feeling in a little "
                "more detail, and I can help prepare a note for your doctor if needed."
            )
        return (
            f"{disclaimer} {vitals_context} I do not see emergency red flags in what you "
            "shared. Keep monitoring, and tell me right away if symptoms worsen."
        )

    def _build_doctor_summary(
        self,
        patient: Patient,
        patient_message: str,
        urgency: ChatUrgency,
        action: ChatRecommendedAction,
        vitals_context: str,
    ) -> str:
        context = []
        if patient.conditions:
            context.append(f"Conditions: {', '.join(patient.conditions)}.")
        if patient.medications:
            context.append(f"Medications: {', '.join(patient.medications)}.")
        if patient.allergies:
            context.append(f"Allergies: {', '.join(patient.allergies)}.")
        if patient.care_notes:
            context.append(f"Care notes: {patient.care_notes}")
        clinical_context = " ".join(context) if context else "No clinical profile details listed."
        return (
            f"Patient reports: {patient_message}. "
            f"Urgency: {urgency.value}. Recommended action: {action.value}. "
            f"{vitals_context} {clinical_context}"
        )


def _clean_message(message: str) -> str:
    return " ".join(message.strip().split())


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _phrase_hits(text: str, phrases: tuple[str, ...]) -> list[str]:
    return [phrase for phrase in phrases if _contains_non_negated(text, phrase)]


def _contains_non_negated(text: str, phrase: str) -> bool:
    start = text.find(phrase)
    while start >= 0:
        prefix = text[max(0, start - 24):start]
        if not re.search(
            r"\b(no|not|without|denies|deny|do not have|don't have|dont have)\s+$",
            prefix,
        ):
            return True
        start = text.find(phrase, start + 1)
    return False


def _vital_flags(
    patient: Patient,
    latest: Optional[HealthRecord],
) -> tuple[list[str], ChatUrgency]:
    if latest is None:
        return [], ChatUrgency.ROUTINE

    thresholds = patient.thresholds
    flags = []
    severe = False
    if latest.heart_rate < thresholds.heart_rate_min:
        flags.append("heart rate below personalized range")
        severe = latest.heart_rate <= max(40, thresholds.heart_rate_min - 15)
    elif latest.heart_rate > thresholds.heart_rate_max:
        flags.append("heart rate above personalized range")
        severe = latest.heart_rate >= min(145, thresholds.heart_rate_max + 30)

    if latest.body_temperature < thresholds.temperature_min:
        flags.append("temperature below personalized range")
        severe = severe or latest.body_temperature <= max(35.0, thresholds.temperature_min - 1.0)
    elif latest.body_temperature > thresholds.temperature_max:
        flags.append("temperature above personalized range")
        severe = severe or latest.body_temperature >= min(39.5, thresholds.temperature_max + 1.0)

    if severe:
        return flags, ChatUrgency.URGENT
    if flags:
        return flags, ChatUrgency.WATCH
    return [], ChatUrgency.ROUTINE


def _vitals_context(patient: Patient, latest: Optional[HealthRecord]) -> str:
    if latest is None:
        return "No recent wearable reading is available."

    thresholds = patient.thresholds
    notes = []
    if latest.heart_rate < thresholds.heart_rate_min or latest.heart_rate > thresholds.heart_rate_max:
        notes.append("heart rate is outside the personalized range")
    if (
        latest.body_temperature < thresholds.temperature_min
        or latest.body_temperature > thresholds.temperature_max
    ):
        notes.append("temperature is outside the personalized range")

    base = (
        f"Latest wearable reading: HR {latest.heart_rate} bpm and temperature "
        f"{latest.body_temperature:.1f} C."
    )
    if notes:
        return f"{base} Note: {'; '.join(notes)}."
    return f"{base} Both are within the personalized thresholds."
