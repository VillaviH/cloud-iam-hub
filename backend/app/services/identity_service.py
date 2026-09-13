"""IdentityService — el orquestador cross-cloud.

Este es el corazón narrativo de la demo. En el diagrama de arquitectura
(diagrams/cloud-iam-hub.drawio) esta responsabilidad está repartida entre
Firestore + Eventarc + Cloud Run Workers. En esta primera versión del
código el mismo flujo se implementa con un fan-out `asyncio.gather`
directo desde la API — misma historia arquitectónica (intención primero,
luego ejecución en paralelo en las 3 nubes, luego auditoría), con menos
piezas de infraestructura que puedan fallar la noche antes de una charla.

Migrar esto a Eventarc real (desacoplar la escritura en Firestore de la
ejecución del fan-out) es el "next step" documentado en el README para
quien tome este repo como regalo y quiera llevarlo más lejos.

Flujo de onboard():
  1. Crear Identity y escribirla en Firestore.
  2. Crear un Assignment PENDING por cada provider solicitado (esto es
     la "intención").
  3. Fan-out en paralelo: cada Assignment dispara adapter.onboard().
  4. Cada resultado actualiza el Assignment (APPLIED/FAILED) y agrega
     una AuditEntry (éxito o error) con el mismo correlation_id.

offboard() reutiliza exactamente el mismo esqueleto, invocando
adapter.offboard() en vez de onboard().
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional
from uuid import uuid4

from app.adapters.base import CloudAdapter
from app.models.unified import (
    Assignment,
    AssignmentStatus,
    AuditAction,
    AuditEntry,
    CloudProvider,
    Identity,
)
from app.repositories.base import IdentityRepository

logger = logging.getLogger(__name__)

_ALL_PROVIDERS = [CloudProvider.AWS, CloudProvider.GCP, CloudProvider.AZURE]
_DEMO_ACTOR = "cloud-iam-hub-demo"


class IdentityService:
    def __init__(self, repo: IdentityRepository, adapters: dict[CloudProvider, CloudAdapter]) -> None:
        self._repo = repo
        self._adapters = adapters

    async def onboard(
        self,
        *,
        display_name: str,
        email: Optional[str],
        role_key: str,
        providers: Optional[list[CloudProvider]] = None,
    ) -> tuple[str, Identity, list[Assignment]]:
        correlation_id = f"corr-{uuid4().hex[:12]}"
        target_providers = providers or _ALL_PROVIDERS

        identity = Identity(display_name=display_name, email=email)
        self._repo.save_identity(identity)

        assignments = [
            Assignment(identity_id=identity.id, provider=provider, role_key=role_key)
            for provider in target_providers
        ]
        for assignment in assignments:
            self._repo.save_assignment(assignment)

        await self._fan_out(
            action=AuditAction.ONBOARD,
            identity=identity,
            assignments=assignments,
            correlation_id=correlation_id,
            role_key=role_key,
        )

        return correlation_id, identity, assignments

    async def offboard(
        self,
        *,
        identity_id: str,
        providers: Optional[list[CloudProvider]] = None,
    ) -> tuple[str, list[Assignment]]:
        correlation_id = f"corr-{uuid4().hex[:12]}"

        identity = self._repo.get_identity(identity_id)
        if identity is None:
            raise ValueError(f"Identity {identity_id} no existe")

        existing_assignments = self._repo.get_assignments_for_identity(identity_id)
        target_providers = set(providers) if providers else {a.provider for a in existing_assignments}

        relevant = [a for a in existing_assignments if a.provider in target_providers]

        await self._fan_out(
            action=AuditAction.OFFBOARD,
            identity=identity,
            assignments=relevant,
            correlation_id=correlation_id,
            role_key=None,
        )

        return correlation_id, relevant

    async def _fan_out(
        self,
        *,
        action: AuditAction,
        identity: Identity,
        assignments: list[Assignment],
        correlation_id: str,
        role_key: Optional[str],
    ) -> None:
        """Dispara los adapters de todos los assignments EN PARALELO.

        Este `asyncio.gather` es el fan-out del diagrama: en producción
        lo haría Eventarc despachando un evento por Assignment hacia
        Cloud Run Workers; aquí lo hace la propia API, en el mismo
        request, para simplificar el despliegue de la demo.
        """
        tasks = [
            self._apply_single(action=action, identity=identity, assignment=assignment, correlation_id=correlation_id, role_key=role_key)
            for assignment in assignments
        ]
        await asyncio.gather(*tasks)

    async def _apply_single(
        self,
        *,
        action: AuditAction,
        identity: Identity,
        assignment: Assignment,
        correlation_id: str,
        role_key: Optional[str],
    ) -> None:
        adapter = self._adapters[assignment.provider]

        try:
            if action == AuditAction.ONBOARD:
                result = await adapter.onboard(
                    identity_id=identity.id,
                    display_name=identity.display_name,
                    role_key=role_key or assignment.role_key,
                )
            else:
                result = await adapter.offboard(
                    identity_id=identity.id,
                    provider_ref=assignment.provider_ref,
                )
        except Exception as exc:  # noqa: BLE001 - un adapter no debe tumbar el fan-out completo
            logger.exception("Adapter %s falló en %s para %s", assignment.provider, action, identity.id)
            self._record_failure(assignment=assignment, action=action, error=str(exc))
            self._append_audit(
                correlation_id=correlation_id,
                identity_id=identity.id,
                provider=assignment.provider,
                action=action,
                success=False,
                error=str(exc),
            )
            return

        if result.success:
            assignment.status = (
                AssignmentStatus.APPLIED if action == AuditAction.ONBOARD else AssignmentStatus.REVOKED
            )
            assignment.provider_ref = result.provider_ref or assignment.provider_ref
            assignment.error = None
        else:
            assignment.status = AssignmentStatus.FAILED
            assignment.error = result.error

        self._repo.save_assignment(assignment)

        self._append_audit(
            correlation_id=correlation_id,
            identity_id=identity.id,
            provider=assignment.provider,
            action=action,
            success=result.success,
            error=result.error,
            before=result.before,
            after=result.after,
        )

    def _record_failure(self, *, assignment: Assignment, action: AuditAction, error: str) -> None:
        assignment.status = AssignmentStatus.FAILED
        assignment.error = error
        self._repo.save_assignment(assignment)

    def _append_audit(
        self,
        *,
        correlation_id: str,
        identity_id: str,
        provider: CloudProvider,
        action: AuditAction,
        success: bool,
        error: Optional[str] = None,
        before: Optional[dict] = None,
        after: Optional[dict] = None,
    ) -> None:
        entry = AuditEntry(
            correlation_id=correlation_id,
            identity_id=identity_id,
            provider=provider,
            action=action,
            actor=_DEMO_ACTOR,
            before=before,
            after=after,
            success=success,
            error=error,
        )
        self._repo.append_audit(entry)
