"""InMemoryRepository — implementación en memoria del mismo contrato que
FirestoreRepository. Se usa en modo sandbox cuando no hay un proyecto GCP
configurado (o simplemente para desarrollo local rápido sin credenciales).
"""

from __future__ import annotations

from app.models.unified import Assignment, AuditEntry, Identity


class InMemoryRepository:
    def __init__(self) -> None:
        self._identities: dict[str, Identity] = {}
        self._assignments: dict[str, Assignment] = {}
        self._audit: list[AuditEntry] = []

    def save_identity(self, identity: Identity) -> None:
        self._identities[identity.id] = identity

    def get_identity(self, identity_id: str) -> Identity | None:
        return self._identities.get(identity_id)

    def save_assignment(self, assignment: Assignment) -> None:
        self._assignments[assignment.id] = assignment

    def get_assignments_for_identity(self, identity_id: str) -> list[Assignment]:
        return [a for a in self._assignments.values() if a.identity_id == identity_id]

    def append_audit(self, entry: AuditEntry) -> None:
        self._audit.append(entry)

    def get_audit_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        return sorted(
            (e for e in self._audit if e.correlation_id == correlation_id),
            key=lambda e: e.timestamp,
        )

    def get_recent_audit(self, limit: int = 50) -> list[AuditEntry]:
        return sorted(self._audit, key=lambda e: e.timestamp, reverse=True)[:limit]
