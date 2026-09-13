"""Protocolo de repositorio — implementado por FirestoreRepository (real)
y por InMemoryRepository (plan B en tarima, ver mismo espíritu que
MockAdapter: si algo falla la noche antes de la charla, el hub sigue
funcionando end-to-end, solo que sin persistencia real).
"""

from __future__ import annotations

from typing import Protocol

from app.models.unified import Assignment, AuditEntry, Identity


class IdentityRepository(Protocol):
    def save_identity(self, identity: Identity) -> None: ...

    def get_identity(self, identity_id: str) -> Identity | None: ...

    def save_assignment(self, assignment: Assignment) -> None: ...

    def get_assignments_for_identity(self, identity_id: str) -> list[Assignment]: ...

    def append_audit(self, entry: AuditEntry) -> None: ...

    def get_audit_for_correlation(self, correlation_id: str) -> list[AuditEntry]: ...

    def get_recent_audit(self, limit: int = 50) -> list[AuditEntry]: ...
