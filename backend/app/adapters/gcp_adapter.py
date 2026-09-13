"""GcpAdapter — gobierna bindings de IAM sobre un proyecto/recurso de GCP.

Lo que este adapter demuestra en vivo (ver docs/IAM_CLOUD_MAPPING.md):

`setIamPolicy()` REEMPLAZA la política completa del recurso, no la
mezcla con lo existente. El único camino correcto es:

    1. getIamPolicy()                  -> trae la policy + su etag
    2. mutar los bindings en memoria    -> agregar o quitar el member
    3. setIamPolicy(policy_con_etag)    -> reintentar si la API responde
                                            409 ABORTED (alguien más
                                            escribió la policy entre el
                                            get y el set)

Este adapter no crea/borra un IAM User (GCP no tiene ese concepto para
service accounts externos de la misma forma que AWS): el "principal" de
demo es un Service Account ya existente (creado por Terraform, ver
infra/gcp/main.tf -> demo_target_principal), y lo que el adapter
onboardea/offboardea es el BINDING de ese principal sobre el recurso
gobernado (el propio proyecto, por simplicidad de la demo).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from google.api_core.exceptions import Aborted
from google.cloud import resourcemanager_v3

from app.adapters.base import AdapterResult, CloudAdapter
from app.config import Settings
from app.models.unified import CloudProvider

logger = logging.getLogger(__name__)

_ROLE_MAP = {
    "viewer": "roles/viewer",
    "editor": "roles/editor",
}

_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 0.5


def _member_for(identity_id: str, settings: Settings) -> str:
    """El member que se agrega/quita del binding.

    Se usa el service account de demo creado por Terraform
    (demo_target_principal) como stand-in del "principal gobernado";
    identity_id queda registrado como metadata en Firestore/Audit para
    trazabilidad, no como parte del member de IAM.
    """
    return f"serviceAccount:{settings.gcp_demo_target_resource_member}"


class GcpAdapter(CloudAdapter):
    provider = CloudProvider.GCP

    def __init__(self, settings: Settings, client: Optional[resourcemanager_v3.ProjectsClient] = None) -> None:
        self._settings = settings
        self._client = client or resourcemanager_v3.ProjectsClient()
        self._resource_name = f"projects/{settings.gcp_project_id}"

    async def onboard(self, *, identity_id: str, display_name: str, role_key: str) -> AdapterResult:
        role = _ROLE_MAP.get(role_key, _ROLE_MAP["viewer"])
        member = _member_for(identity_id, self._settings)

        try:
            before, after = self._mutate_policy(add_member=member, role=role, remove_member=None)
            return AdapterResult(success=True, provider_ref=member, before=before, after=after)
        except Exception as exc:  # noqa: BLE001 - se registra y se propaga como resultado
            logger.exception("GcpAdapter.onboard failed for %s", identity_id)
            return AdapterResult(success=False, error=str(exc))

    async def offboard(self, *, identity_id: str, provider_ref: Optional[str]) -> AdapterResult:
        member = provider_ref or _member_for(identity_id, self._settings)

        try:
            before, after = self._mutate_policy(add_member=None, role=None, remove_member=member)
            return AdapterResult(success=True, provider_ref=member, before=before, after=after)
        except Exception as exc:  # noqa: BLE001
            logger.exception("GcpAdapter.offboard failed for %s", identity_id)
            return AdapterResult(success=False, error=str(exc))

    def _mutate_policy(
        self,
        *,
        add_member: Optional[str],
        role: Optional[str],
        remove_member: Optional[str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Implementa el ciclo get -> mutar -> set(etag) con reintentos.

        Este método es, literalmente, la corrección al error más común
        al integrar con GCP IAM: llamar setIamPolicy() con solo el binding
        nuevo y borrar por accidente todos los demás.
        """

        last_error: Optional[Exception] = None

        for attempt in range(_MAX_RETRIES):
            policy = self._client.get_iam_policy(resource=self._resource_name)
            before_snapshot = self._policy_to_dict(policy)

            if add_member and role:
                self._add_binding(policy, role=role, member=add_member)
            if remove_member:
                self._remove_member(policy, member=remove_member)

            try:
                updated = self._client.set_iam_policy(
                    resource=self._resource_name,
                    policy=policy,
                )
                return before_snapshot, self._policy_to_dict(updated)
            except Aborted as exc:
                # 409 ABORTED: el etag ya no es válido porque otro
                # escritor modificó la policy entre nuestro get y set.
                # Se reintenta el ciclo completo desde el get.
                last_error = exc
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue

        raise RuntimeError(
            f"No se pudo actualizar la IAM policy tras {_MAX_RETRIES} intentos "
            f"(conflictos de etag consecutivos): {last_error}"
        )

    @staticmethod
    def _add_binding(policy: Any, *, role: str, member: str) -> None:
        for binding in policy.bindings:
            if binding.role == role:
                if member not in binding.members:
                    binding.members.append(member)
                return
        policy.bindings.add(role=role, members=[member])

    @staticmethod
    def _remove_member(policy: Any, *, member: str) -> None:
        for binding in list(policy.bindings):
            if member in binding.members:
                binding.members.remove(member)

    @staticmethod
    def _policy_to_dict(policy: Any) -> dict[str, Any]:
        return {
            "etag": policy.etag.hex() if isinstance(policy.etag, bytes) else str(policy.etag),
            "bindings": [
                {"role": b.role, "members": list(b.members)} for b in policy.bindings
            ],
        }
