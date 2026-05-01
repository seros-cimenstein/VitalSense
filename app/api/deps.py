"""FastAPI dependency providers — wires the object graph."""
from __future__ import annotations

import os
from functools import lru_cache

from app.core import AnomalyDetectionEngine
from app.db import Repository, get_repository
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
    sos = SOSService(repo, notif_service)
    engine = AnomalyDetectionEngine(repo, sos)
    return repo, sos, engine


def get_repo() -> Repository:
    return _build_graph()[0]


def get_sos() -> SOSService:
    return _build_graph()[1]


def get_engine() -> AnomalyDetectionEngine:
    return _build_graph()[2]


def reset_graph() -> None:
    """Test helper — drop the cached object graph."""
    _build_graph.cache_clear()
