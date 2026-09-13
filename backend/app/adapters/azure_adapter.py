"""AzureAdapter — gobierna identidad (Entra ID) y permisos (RBAC) en Azure.

Lo que este adapter demuestra en vivo (ver docs/IAM_CLOUD_MAPPING.md):

Identidad y permisos viven en dos planos separados con dos SDKs
distintos, y no hay un solo `assign()` que resuelva ambos:

  - Entra ID (Microsoft Graph): quién es el usuario, si está habilitado
    (`accountEnabled`). Se gestiona con el SDK de Graph.
  - Azure RBAC (`azure-mgmt-authorization`): qué puede hacer ese usuario,
    vía `roleAssignments` sobre un scope (subscription / resource group /
    recurso). Es una API de gestión de recursos completamente distinta.

El onboarding real requiere DOS llamadas a DOS sistemas; si solo se hace
una, la operación queda a medias (usuario creado sin permisos, o un
roleAssignment sobre una identidad que luego no se puede deshabilitar
desde ahí).

Antes de cualquier llamada real, se verifica explícitamente (ver
app.config.assert_azure_tenant_is_safe) que el tenant activo sea el
declarado como propio — este proyecto es un repo público y nunca debe
ejecutar operaciones de IAM reales contra un directorio no declarado.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import uuid4

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import ClientSecretCredential
from azure.mgmt.authorization import AuthorizationManagementClient
from msgraph import GraphServiceClient

from app.adapters.base import AdapterResult, CloudAdapter
from app.config import Settings, assert_azure_tenant_is_safe
from app.models.unified import CloudProvider

logger = logging.getLogger(__name__)

# Role Definition ID built-in de Azure para el rol "Reader" (solo lectura).
# Es un GUID fijo y público, documentado por Microsoft, no un secreto.
_READER_ROLE_DEFINITION_ID_SUFFIX = "/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7"

_DOMAIN_SUFFIX_PLACEHOLDER = "example.onmicrosoft.com"  # se sobreescribe por settings en runtime


def _upn_for(identity_id: str, settings: Settings) -> str:
    domain = settings.azure_upn_domain or _DOMAIN_SUFFIX_PLACEHOLDER
    return f"demo-{identity_id}@{domain}"


class AzureAdapter(CloudAdapter):
    provider = CloudProvider.AZURE

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._credential = ClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
        self._graph = GraphServiceClient(credentials=self._credential)
        self._authorization = AuthorizationManagementClient(
            self._credential, settings.azure_subscription_id
        )

    async def onboard(self, *, identity_id: str, display_name: str, role_key: str) -> AdapterResult:
        assert_azure_tenant_is_safe(self._settings.azure_tenant_id, self._settings)

        upn = _upn_for(identity_id, self._settings)
        try:
            before = await self._safe_get_user(upn)

            user = await self._create_or_enable_user(upn=upn, display_name=display_name)

            role_assignment = self._assign_reader_role(principal_id=user["id"])

            after = await self._safe_get_user(upn)
            after = {**(after or {}), "roleAssignmentId": role_assignment}

            return AdapterResult(success=True, provider_ref=user["id"], before=before, after=after)

        except Exception as exc:  # noqa: BLE001
            logger.exception("AzureAdapter.onboard failed for %s", upn)
            return AdapterResult(success=False, error=str(exc))

    async def offboard(self, *, identity_id: str, provider_ref: Optional[str]) -> AdapterResult:
        assert_azure_tenant_is_safe(self._settings.azure_tenant_id, self._settings)

        upn = _upn_for(identity_id, self._settings)
        try:
            before = await self._safe_get_user(upn)
            if before is None:
                return AdapterResult(success=True, before=None, after=None)

            user_id = provider_ref or before["id"]

            # 1) Quitar el roleAssignment (plano de autorización / RBAC).
            self._remove_role_assignments(principal_id=user_id)

            # 2) Deshabilitar la identidad en Entra ID (plano de identidad).
            #    accountEnabled=False es el equivalente de Azure a un
            #    "disable"; no se elimina el usuario para conservar el
            #    antecedente auditable.
            await self._graph.users.by_user_id(user_id).patch(
                {"accountEnabled": False}
            )

            after = await self._safe_get_user(upn)
            return AdapterResult(success=True, before=before, after=after)

        except Exception as exc:  # noqa: BLE001
            logger.exception("AzureAdapter.offboard failed for %s", upn)
            return AdapterResult(success=False, error=str(exc))

    async def _create_or_enable_user(self, *, upn: str, display_name: str) -> dict[str, Any]:
        existing = await self._safe_get_user(upn)
        if existing is not None:
            if not existing.get("accountEnabled", True):
                await self._graph.users.by_user_id(existing["id"]).patch(
                    {"accountEnabled": True}
                )
            return existing

        temp_password = uuid4().hex + "Aa1!"
        new_user = await self._graph.users.post(
            {
                "accountEnabled": True,
                "displayName": display_name,
                "mailNickname": upn.split("@")[0],
                "userPrincipalName": upn,
                "passwordProfile": {
                    "forceChangePasswordNextSignIn": True,
                    "password": temp_password,
                },
            }
        )
        return {"id": new_user.id, "userPrincipalName": upn, "accountEnabled": True}

    async def _safe_get_user(self, upn: str) -> Optional[dict[str, Any]]:
        try:
            user = await self._graph.users.by_user_id(upn).get()
            return {
                "id": user.id,
                "userPrincipalName": user.user_principal_name,
                "accountEnabled": user.account_enabled,
            }
        except ResourceNotFoundError:
            return None
        except Exception as exc:  # noqa: BLE001
            # El SDK de Graph puede lanzar su propio ODataError para 404;
            # se trata como "no encontrado" en vez de propagar.
            if "does not exist" in str(exc) or "Request_ResourceNotFound" in str(exc):
                return None
            raise

    def _assign_reader_role(self, *, principal_id: str) -> str:
        scope = (
            f"/subscriptions/{self._settings.azure_subscription_id}"
            f"/resourceGroups/{self._settings.azure_resource_group}"
        )
        role_definition_id = f"/subscriptions/{self._settings.azure_subscription_id}{_READER_ROLE_DEFINITION_ID_SUFFIX}"
        assignment_name = str(uuid4())

        result = self._authorization.role_assignments.create(
            scope=scope,
            role_assignment_name=assignment_name,
            parameters={
                "role_definition_id": role_definition_id,
                "principal_id": principal_id,
            },
        )
        return result.id

    def _remove_role_assignments(self, *, principal_id: str) -> None:
        scope = (
            f"/subscriptions/{self._settings.azure_subscription_id}"
            f"/resourceGroups/{self._settings.azure_resource_group}"
        )
        assignments = self._authorization.role_assignments.list_for_scope(
            scope=scope, filter=f"principalId eq '{principal_id}'"
        )
        for assignment in assignments:
            self._authorization.role_assignments.delete_by_id(assignment.id)
