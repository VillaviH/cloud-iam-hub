"""Fábrica de repositorio — mismo espíritu que adapter_factory.py.

En modo sandbox, o si no hay gcp_project_id configurado, se usa el
repositorio en memoria (sin credenciales, sin red). En modo live con
proyecto configurado, se usa Firestore real.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.repositories.base import IdentityRepository
from app.repositories.memory_repo import InMemoryRepository


def build_repository(settings: Settings) -> IdentityRepository:
    if settings.cloud_iam_mode == "sandbox" or not settings.gcp_project_id:
        return InMemoryRepository()

    from app.repositories.firestore_repo import FirestoreRepository

    return FirestoreRepository(project=settings.gcp_project_id)


@lru_cache
def get_repository() -> IdentityRepository:
    return build_repository(get_settings())
