"""Health chat model providers.

The default model is a small local triage model so demos work offline. If an
API URL is configured, the service can delegate the same structured task to an
external small model and fall back locally when that API is unavailable.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

import httpx

from app.models import (
    ChatRecommendedAction,
    ChatUrgency,
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

SYSTEM_POLICY = (
    "You are VitalSense health support. Do not diagnose, do not change "
    "medication instructions, and prioritize emergency services for red flags. "
    "Return JSON with reply, urgency, recommended_action, doctor_summary, and signals. "
    "If the patient reports chest pain, severe breathing trouble, fainting, "
    "stroke-like symptoms, anaphylaxis, or self-harm intent, classify as emergency."
)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash-lite"


@dataclass(frozen=True)
class HealthChatModelOutput:
    reply: str
    urgency: ChatUrgency
    recommended_action: ChatRecommendedAction
    doctor_summary: str
    signals: list[str] = field(default_factory=list)
    provider: str = "local"
    model_name: str = "vitalsense-local-triage-v1"
    confidence: float = 0.0


class HealthChatModel(Protocol):
    def generate(
        self,
        patient: Patient,
        patient_message: str,
        latest_record: Optional[HealthRecord],
    ) -> HealthChatModelOutput:
        ...


class LocalTriageHealthChatModel:
    """Small baked-in model for safe offline triage."""

    def __init__(self, model_name: str = "vitalsense-local-triage-v1") -> None:
        self.model_name = model_name

    def generate(
        self,
        patient: Patient,
        patient_message: str,
        latest_record: Optional[HealthRecord],
    ) -> HealthChatModelOutput:
        urgency, action, signals = self._classify(patient, patient_message, latest_record)
        vitals_context = _vitals_context(patient, latest_record)
        reply = self._build_reply(patient_message, urgency, action, signals, vitals_context)
        doctor_summary = _build_doctor_summary(
            patient=patient,
            patient_message=patient_message,
            urgency=urgency,
            action=action,
            vitals_context=vitals_context,
        )
        return HealthChatModelOutput(
            reply=reply,
            urgency=urgency,
            recommended_action=action,
            doctor_summary=doctor_summary,
            signals=signals,
            provider="local",
            model_name=self.model_name,
            confidence=_confidence_for(urgency, signals),
        )

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


class APIHealthChatModel:
    """External API backed model using the same structured contract."""

    def __init__(
        self,
        api_url: str,
        api_token: Optional[str] = None,
        model_name: str = "vitalsense-health-chat-small",
        timeout_seconds: float = 12.0,
        fallback: Optional[HealthChatModel] = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_url = api_url
        self.api_token = api_token
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.fallback = fallback or LocalTriageHealthChatModel()
        self.transport = transport

    def generate(
        self,
        patient: Patient,
        patient_message: str,
        latest_record: Optional[HealthRecord],
    ) -> HealthChatModelOutput:
        try:
            payload = self._request_payload(patient, patient_message, latest_record)
            headers = {"Content-Type": "application/json"}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(self.api_url, json=payload, headers=headers)
                response.raise_for_status()
            output = self._parse_response(response.json(), patient, patient_message, latest_record)
            return _apply_safety_floor(
                output,
                self.fallback.generate(patient, patient_message, latest_record),
            )
        except Exception:
            fallback = self.fallback.generate(patient, patient_message, latest_record)
            return HealthChatModelOutput(
                reply=fallback.reply,
                urgency=fallback.urgency,
                recommended_action=fallback.recommended_action,
                doctor_summary=fallback.doctor_summary,
                signals=fallback.signals + ["api fallback"],
                provider=fallback.provider,
                model_name=fallback.model_name,
                confidence=fallback.confidence,
            )

    def _request_payload(
        self,
        patient: Patient,
        patient_message: str,
        latest_record: Optional[HealthRecord],
    ) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "system": SYSTEM_POLICY,
            "message": patient_message,
            "patient": patient.model_dump(mode="json"),
            "latest_record": latest_record.model_dump(mode="json") if latest_record else None,
            "allowed_urgencies": [item.value for item in ChatUrgency],
            "allowed_actions": [item.value for item in ChatRecommendedAction],
        }

    def _parse_response(
        self,
        payload: dict[str, Any],
        patient: Patient,
        patient_message: str,
        latest_record: Optional[HealthRecord],
    ) -> HealthChatModelOutput:
        body = _extract_payload(payload)
        reply = str(body.get("reply") or body.get("response") or "").strip()
        urgency = _enum_value(ChatUrgency, body.get("urgency"), ChatUrgency.ROUTINE)
        action = _enum_value(
            ChatRecommendedAction,
            body.get("recommended_action"),
            ChatRecommendedAction.NONE,
        )
        action = _minimum_action_for(urgency, action)
        signals = _clean_signals(body.get("signals"))
        vitals_context = _vitals_context(patient, latest_record)
        doctor_summary = str(body.get("doctor_summary") or "").strip()

        if not reply:
            raise ValueError("chat API response missing reply")
        if not doctor_summary:
            doctor_summary = _build_doctor_summary(
                patient=patient,
                patient_message=patient_message,
                urgency=urgency,
                action=action,
                vitals_context=vitals_context,
            )

        confidence = body.get("confidence", 0.7)
        return HealthChatModelOutput(
            reply=reply,
            urgency=urgency,
            recommended_action=action,
            doctor_summary=doctor_summary,
            signals=signals or ["api model"],
            provider="api",
            model_name=str(body.get("model") or self.model_name),
            confidence=_float_between_zero_and_one(confidence),
        )


class GeminiHealthChatModel:
    """Gemini generateContent provider for low-latency Flash-Lite health chat."""

    def __init__(
        self,
        api_key: str,
        model_name: str = GEMINI_DEFAULT_MODEL,
        base_url: str = GEMINI_BASE_URL,
        timeout_seconds: float = 12.0,
        temperature: float = 0.2,
        fallback: Optional[HealthChatModel] = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model_name = _normalize_gemini_model_name(model_name)
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.fallback = fallback or LocalTriageHealthChatModel()
        self.transport = transport

    def generate(
        self,
        patient: Patient,
        patient_message: str,
        latest_record: Optional[HealthRecord],
    ) -> HealthChatModelOutput:
        try:
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            }
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    self._generate_content_url(),
                    json=self._request_payload(patient, patient_message, latest_record),
                    headers=headers,
                )
                response.raise_for_status()
            output = self._parse_response(
                response.json(),
                patient,
                patient_message,
                latest_record,
            )
            return _apply_safety_floor(
                output,
                self.fallback.generate(patient, patient_message, latest_record),
            )
        except Exception:
            fallback = self.fallback.generate(patient, patient_message, latest_record)
            return HealthChatModelOutput(
                reply=fallback.reply,
                urgency=fallback.urgency,
                recommended_action=fallback.recommended_action,
                doctor_summary=fallback.doctor_summary,
                signals=fallback.signals + ["gemini fallback"],
                provider=fallback.provider,
                model_name=fallback.model_name,
                confidence=fallback.confidence,
            )

    def _generate_content_url(self) -> str:
        return f"{self.base_url}/v1beta/models/{self.model_name}:generateContent"

    def _request_payload(
        self,
        patient: Patient,
        patient_message: str,
        latest_record: Optional[HealthRecord],
    ) -> dict[str, Any]:
        return {
            "systemInstruction": {
                "parts": [{"text": SYSTEM_POLICY}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": json.dumps(
                                _model_task(patient, patient_message, latest_record),
                                ensure_ascii=True,
                            ),
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": self.temperature,
                "topP": 0.8,
                "maxOutputTokens": 1200,
                "responseMimeType": "application/json",
            },
        }

    def _parse_response(
        self,
        payload: dict[str, Any],
        patient: Patient,
        patient_message: str,
        latest_record: Optional[HealthRecord],
    ) -> HealthChatModelOutput:
        body = _extract_gemini_payload(payload)
        reply = str(body.get("reply") or body.get("response") or "").strip()
        urgency = _enum_value(ChatUrgency, body.get("urgency"), ChatUrgency.ROUTINE)
        action = _enum_value(
            ChatRecommendedAction,
            body.get("recommended_action"),
            ChatRecommendedAction.NONE,
        )
        action = _minimum_action_for(urgency, action)
        signals = _clean_signals(body.get("signals"))
        vitals_context = _vitals_context(patient, latest_record)
        doctor_summary = str(body.get("doctor_summary") or "").strip()

        if not reply:
            raise ValueError("gemini response missing reply")
        if not doctor_summary:
            doctor_summary = _build_doctor_summary(
                patient=patient,
                patient_message=patient_message,
                urgency=urgency,
                action=action,
                vitals_context=vitals_context,
            )

        confidence = body.get("confidence", 0.7)
        return HealthChatModelOutput(
            reply=reply,
            urgency=urgency,
            recommended_action=action,
            doctor_summary=doctor_summary,
            signals=signals or ["gemini model"],
            provider="gemini",
            model_name=str(body.get("model") or self.model_name),
            confidence=_float_between_zero_and_one(confidence),
        )


def build_health_chat_model_from_env() -> HealthChatModel:
    _load_dotenv_if_present()
    local = LocalTriageHealthChatModel(
        model_name=os.getenv("VITALSENSE_CHAT_LOCAL_MODEL", "vitalsense-local-triage-v1")
    )
    api_url = os.getenv("VITALSENSE_CHAT_API_URL", "").strip()
    provider = os.getenv("VITALSENSE_CHAT_MODEL_PROVIDER", "").strip().lower()
    if provider in {"gemini", "google", "google-gemini"}:
        api_key = (
            os.getenv("VITALSENSE_GEMINI_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        ).strip()
        if api_key:
            return GeminiHealthChatModel(
                api_key=api_key,
                model_name=os.getenv("VITALSENSE_CHAT_GEMINI_MODEL", GEMINI_DEFAULT_MODEL),
                base_url=os.getenv("VITALSENSE_GEMINI_BASE_URL", GEMINI_BASE_URL),
                timeout_seconds=_float_env("VITALSENSE_CHAT_API_TIMEOUT", 12.0),
                temperature=_float_env("VITALSENSE_CHAT_GEMINI_TEMPERATURE", 0.2),
                fallback=local,
            )
        return local
    if api_url and provider in {"", "api", "external"}:
        return APIHealthChatModel(
            api_url=api_url,
            api_token=os.getenv("VITALSENSE_CHAT_API_TOKEN"),
            model_name=os.getenv("VITALSENSE_CHAT_API_MODEL", "vitalsense-health-chat-small"),
            timeout_seconds=_float_env("VITALSENSE_CHAT_API_TIMEOUT", 12.0),
            fallback=local,
        )
    return local


def _model_task(
    patient: Patient,
    patient_message: str,
    latest_record: Optional[HealthRecord],
) -> dict[str, Any]:
    return {
        "task": (
            "Classify the patient message conservatively and return JSON only. "
            "Do not diagnose. Use the latest wearable reading as context, not proof."
        ),
        "message": patient_message,
        "patient_context": _patient_context(patient),
        "latest_record": _record_context(latest_record),
        "allowed_urgencies": [item.value for item in ChatUrgency],
        "allowed_actions": [item.value for item in ChatRecommendedAction],
        "required_json_shape": {
            "reply": "patient-facing response",
            "urgency": "routine | watch | urgent | emergency",
            "recommended_action": "none | verify | share_doctor | trigger_sos",
            "doctor_summary": "concise clinical handoff summary",
            "signals": ["matched symptom or vital signal"],
            "confidence": "0.0 to 1.0",
        },
    }


def _patient_context(patient: Patient) -> dict[str, Any]:
    return {
        "age": patient.age,
        "height_cm": patient.height_cm,
        "weight_kg": patient.weight_kg,
        "thresholds": patient.thresholds.model_dump(mode="json"),
        "conditions": patient.conditions,
        "medications": patient.medications,
        "allergies": patient.allergies,
        "care_notes": patient.care_notes,
    }


def _record_context(latest_record: Optional[HealthRecord]) -> Optional[dict[str, Any]]:
    if latest_record is None:
        return None
    return {
        "heart_rate": latest_record.heart_rate,
        "body_temperature": latest_record.body_temperature,
        "daily_steps": latest_record.daily_steps,
        "timestamp": latest_record.timestamp.isoformat(),
    }


def _build_doctor_summary(
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


def _confidence_for(urgency: ChatUrgency, signals: list[str]) -> float:
    if "no red flags detected" in signals:
        return 0.55
    if urgency == ChatUrgency.EMERGENCY:
        return 0.92
    if urgency == ChatUrgency.URGENT:
        return 0.82
    if urgency == ChatUrgency.WATCH:
        return 0.72
    return 0.6


def _apply_safety_floor(
    output: HealthChatModelOutput,
    floor: HealthChatModelOutput,
) -> HealthChatModelOutput:
    if _urgency_rank(output.urgency) >= _urgency_rank(floor.urgency):
        return output
    return HealthChatModelOutput(
        reply=floor.reply,
        urgency=floor.urgency,
        recommended_action=floor.recommended_action,
        doctor_summary=floor.doctor_summary,
        signals=_dedupe(output.signals + floor.signals + ["local safety floor"]),
        provider=output.provider,
        model_name=output.model_name,
        confidence=max(output.confidence, floor.confidence),
    )


def _minimum_action_for(
    urgency: ChatUrgency,
    action: ChatRecommendedAction,
) -> ChatRecommendedAction:
    if urgency == ChatUrgency.EMERGENCY:
        return ChatRecommendedAction.TRIGGER_SOS
    if urgency == ChatUrgency.URGENT and action in {
        ChatRecommendedAction.NONE,
        ChatRecommendedAction.VERIFY,
    }:
        return ChatRecommendedAction.SHARE_DOCTOR
    if urgency == ChatUrgency.WATCH and action == ChatRecommendedAction.NONE:
        return ChatRecommendedAction.VERIFY
    return action


def _urgency_rank(urgency: ChatUrgency) -> int:
    return {
        ChatUrgency.ROUTINE: 0,
        ChatUrgency.WATCH: 1,
        ChatUrgency.URGENT: 2,
        ChatUrgency.EMERGENCY: 3,
    }[urgency]


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _extract_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "choices" not in payload:
        return payload
    choices = payload.get("choices") or []
    if not choices:
        return payload
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message", {}) if isinstance(choice.get("message"), dict) else {}
    content = message.get("content") or choice.get("text") or ""
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        decoded = _json_object_from_text(content)
        return decoded if decoded is not None else {"reply": content}
    return payload


def _extract_gemini_payload(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("candidates") or []
    if not candidates:
        return payload
    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    content = candidate.get("content", {}) if isinstance(candidate.get("content"), dict) else {}
    parts = content.get("parts") or []
    text_parts = [
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    text = "\n".join(part for part in text_parts if part).strip()
    if not text:
        return payload
    decoded = _json_object_from_text(text)
    return decoded if decoded is not None else {"reply": text}


def _json_object_from_text(text: str) -> Optional[dict[str, Any]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        decoded = json.loads(cleaned)
        return decoded if isinstance(decoded, dict) else None
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                decoded = json.loads(cleaned[start:end + 1])
                return decoded if isinstance(decoded, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def _normalize_gemini_model_name(model_name: str) -> str:
    return model_name.strip().removeprefix("models/") or GEMINI_DEFAULT_MODEL


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


_DOTENV_LOADED = False


def _load_dotenv_if_present() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def _enum_value(enum_cls, value, fallback):
    try:
        return enum_cls(str(value))
    except (TypeError, ValueError):
        return fallback


def _clean_signals(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _float_between_zero_and_one(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.7
    return max(0.0, min(1.0, number))
