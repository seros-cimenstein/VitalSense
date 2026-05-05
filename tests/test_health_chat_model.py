"""Tests for health chat model providers."""
from __future__ import annotations

import json

import httpx

from app.models import ChatRecommendedAction, ChatUrgency, Patient
from app.services.health_chat_model import (
    APIHealthChatModel,
    GeminiHealthChatModel,
    LocalTriageHealthChatModel,
    build_health_chat_model_from_env,
)


def test_local_triage_model_flags_emergency_red_flags():
    patient = Patient(
        name="Chat",
        contact_number="+90-555-0000",
        age=55,
        height_cm=170,
        weight_kg=70,
    )
    model = LocalTriageHealthChatModel()

    result = model.generate(patient, "I have chest pain and feel dizzy", None)

    assert result.urgency == ChatUrgency.EMERGENCY
    assert result.recommended_action == ChatRecommendedAction.TRIGGER_SOS
    assert result.provider == "local"
    assert "chest pain" in result.signals


def test_api_health_chat_model_accepts_structured_response():
    patient = Patient(
        name="Chat",
        contact_number="+90-555-0000",
        age=55,
        height_cm=170,
        weight_kg=70,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Bearer ")
        payload = {
            "reply": "Please keep monitoring and share this with your doctor.",
            "urgency": "watch",
            "recommended_action": "share_doctor",
            "doctor_summary": "Patient reports fatigue. No emergency red flags.",
            "signals": ["fatigue"],
            "model": "tiny-health",
            "confidence": 0.74,
        }
        return httpx.Response(200, json=payload)

    model = APIHealthChatModel(
        api_url="https://chat.example.test/respond",
        api_token="test-token",
        model_name="tiny-health",
        transport=httpx.MockTransport(handler),
    )

    result = model.generate(patient, "I feel tired", None)

    assert result.provider == "api"
    assert result.model_name == "tiny-health"
    assert result.urgency == ChatUrgency.WATCH
    assert result.recommended_action == ChatRecommendedAction.SHARE_DOCTOR
    assert result.confidence == 0.74


def test_api_health_chat_model_falls_back_when_api_fails():
    patient = Patient(
        name="Chat",
        contact_number="+90-555-0000",
        age=55,
        height_cm=170,
        weight_kg=70,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "unavailable"})

    model = APIHealthChatModel(
        api_url="https://chat.example.test/respond",
        model_name="tiny-health",
        transport=httpx.MockTransport(handler),
    )

    result = model.generate(patient, "I have chest pain", None)

    assert result.provider == "local"
    assert result.urgency == ChatUrgency.EMERGENCY
    assert "api fallback" in result.signals


def test_gemini_health_chat_model_accepts_generate_content_response():
    patient = Patient(
        name="Chat",
        contact_number="+90-555-0000",
        age=55,
        height_cm=170,
        weight_kg=70,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "test-key"
        assert request.url.path == "/v1beta/models/gemini-2.5-flash-lite:generateContent"
        body = json.loads(request.read().decode())
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"reply":"Please share this with your doctor today.",'
                                        '"urgency":"urgent",'
                                        '"recommended_action":"share_doctor",'
                                        '"doctor_summary":"Patient reports dizziness.",'
                                        '"signals":["dizziness"],'
                                        '"confidence":0.81}'
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    model = GeminiHealthChatModel(
        api_key="test-key",
        model_name="models/gemini-2.5-flash-lite",
        transport=httpx.MockTransport(handler),
    )

    result = model.generate(patient, "I feel dizzy", None)

    assert result.provider == "gemini"
    assert result.model_name == "gemini-2.5-flash-lite"
    assert result.urgency == ChatUrgency.URGENT
    assert result.recommended_action == ChatRecommendedAction.SHARE_DOCTOR
    assert result.confidence == 0.81


def test_gemini_health_chat_model_keeps_local_emergency_floor():
    patient = Patient(
        name="Chat",
        contact_number="+90-555-0000",
        age=55,
        height_cm=170,
        weight_kg=70,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"reply":"Keep monitoring.",'
                                        '"urgency":"routine",'
                                        '"recommended_action":"none",'
                                        '"doctor_summary":"Patient reports chest pain.",'
                                        '"signals":[]}'
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    model = GeminiHealthChatModel(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )

    result = model.generate(patient, "I have chest pain", None)

    assert result.provider == "gemini"
    assert result.urgency == ChatUrgency.EMERGENCY
    assert result.recommended_action == ChatRecommendedAction.TRIGGER_SOS
    assert "local safety floor" in result.signals


def test_build_health_chat_model_from_env_selects_gemini(monkeypatch):
    monkeypatch.setenv("VITALSENSE_CHAT_MODEL_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("VITALSENSE_CHAT_GEMINI_MODEL", "gemini-2.5-flash-lite")

    model = build_health_chat_model_from_env()

    assert isinstance(model, GeminiHealthChatModel)
    assert model.model_name == "gemini-2.5-flash-lite"
