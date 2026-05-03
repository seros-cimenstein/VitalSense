"""FastAPI dependency providers — wires the object graph."""
from __future__ import annotations

import os
from functools import lru_cache

from app.core import AnomalyDetectionEngine
from app.db import Repository, get_repository
from app.auth import create_snapshot_access_token
from app.services import ConsoleNotifier, NotificationService, SOSService
from app.services.notification_service import TwilioNotifier


def _build_notifier():
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_num = os.getenv("TWILIO_FROM_NUMBER")
    if sid and token and from_num:
        return TwilioNotifier(sid, token, from_num)
    return ConsoleNotifier()


@lru_cache(maxsize=1)
def _build_graph() -> tuple[Repository, SOSService, AnomalyDetectionEngine]:
    repo = get_repository()
    notifier = _build_notifier()
    notif_service = NotificationService(notifier)
    snapshot_base_url = os.getenv(
        "VITALSENSE_SNAPSHOT_BASE_URL",
        "https://suzuki-carry-vitalsense-dev.hf.space/doctor/snapshot",
    )

    def snapshot_link(patient_id: str) -> str:
        token = create_snapshot_access_token(patient_id)
        return f"{snapshot_base_url}/{patient_id}?token={token}"

    def verification_prompt(patient, reason, timeout_seconds: float) -> bool:
        return notif_service.send_verification_prompt(
            contact=patient.contact_number,
            patient_name=patient.name,
            detail=reason.detail,
            timeout_seconds=int(timeout_seconds),
        )

    sos = SOSService(
        repo,
        notif_service,
        snapshot_base_url=snapshot_base_url,
        snapshot_link_factory=snapshot_link,
    )
    engine = AnomalyDetectionEngine(
        repo,
        sos,
        verification_notifier=verification_prompt,
    )
    return repo, sos, engine


async def get_repo() -> Repository:
    return _build_graph()[0]


async def get_sos() -> SOSService:
    return _build_graph()[1]


async def get_engine() -> AnomalyDetectionEngine:
    return _build_graph()[2]


def reset_graph() -> None:
    """Test helper — drop the cached object graph."""
    _build_graph.cache_clear()
