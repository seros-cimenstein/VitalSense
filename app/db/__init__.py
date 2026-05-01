"""Storage layer.

Uses Firebase Firestore in production (when VITALSENSE_USE_FIRESTORE=1),
otherwise an in-memory store so the project runs and tests pass with no
external dependencies. The Repository class abstracts which is in use.
"""
from .repository import Repository, get_repository

__all__ = ["Repository", "get_repository"]
