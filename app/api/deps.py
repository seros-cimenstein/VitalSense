"""FastAPI dependency providers — wires the object graph."""
from __future__ import annotations

from functools import lru_cache

from app.core import AnomalyDetectionEngine
from app.db import Repository, get_repository
from app.services import ConsoleNotifier, NotificationService, SOSService


@lru_cache(maxsize=1)
def _build_graph() -> tuple[Repository, SOSService, AnomalyDetectionEngine]:
    repo = get_repository()
    notifier = ConsoleNotifier()
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
