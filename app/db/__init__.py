"""Storage layer.

SQLite is the default runtime backend. Set VITALSENSE_REPOSITORY=memory for
ephemeral demos/tests or VITALSENSE_REPOSITORY=firestore for Firebase.
"""
from .repository import Repository, SQLiteRepository, get_repository

__all__ = ["Repository", "SQLiteRepository", "get_repository"]
