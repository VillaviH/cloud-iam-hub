"""Repositorio Firestore para Identity / Assignment / Audit.

Firestore guarda la INTENCIÓN y el ESTADO del hub. Las colecciones son:

  identities   -> un documento por Identity de demo
  assignments  -> un documento por Assignment (identity_id + provider)
  audit        -> append-only, un documento por AuditEntry

No hay lógica de negocio aquí, solo lectura/escritura. La orquestación
(fan-out hacia los adapters) vive en app/services/identity_service.py.
"""

from __future__ import annotations

from typing import Optional

from google.cloud import firestore

from app.models.unified import Assignment, AuditEntry, Identity

_IDENTITIES = "identities"
_ASSIGNMENTS = "assignments"
_AUDIT = "audit"


class FirestoreRepository:
    def __init__(self, client: Optional[firestore.Client] = None, project: Optional[str] = None) -> None:
        self._client = client or firestore.Client(project=project)

    # --- Identity ---

    def save_identity(self, identity: Identity) -> None:
        self._client.collection(_IDENTITIES).document(identity.id).set(identity.model_dump(mode="json"))

    def get_identity(self, identity_id: str) -> Optional[Identity]:
        doc = self._client.collection(_IDENTITIES).document(identity_id).get()
        if not doc.exists:
            return None
        return Identity.model_validate(doc.to_dict())

    # --- Assignment ---

    def save_assignment(self, assignment: Assignment) -> None:
        self._client.collection(_ASSIGNMENTS).document(assignment.id).set(
            assignment.model_dump(mode="json")
        )

    def get_assignments_for_identity(self, identity_id: str) -> list[Assignment]:
        docs = (
            self._client.collection(_ASSIGNMENTS)
            .where("identity_id", "==", identity_id)
            .stream()
        )
        return [Assignment.model_validate(d.to_dict()) for d in docs]

    # --- Audit (append-only) ---

    def append_audit(self, entry: AuditEntry) -> None:
        self._client.collection(_AUDIT).document(entry.id).set(entry.model_dump(mode="json"))

    def get_audit_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        docs = (
            self._client.collection(_AUDIT)
            .where("correlation_id", "==", correlation_id)
            .order_by("timestamp")
            .stream()
        )
        return [AuditEntry.model_validate(d.to_dict()) for d in docs]

    def get_recent_audit(self, limit: int = 50) -> list[AuditEntry]:
        docs = (
            self._client.collection(_AUDIT)
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        return [AuditEntry.model_validate(d.to_dict()) for d in docs]
