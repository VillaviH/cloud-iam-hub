"""Contrato que TODOS los adapters deben cumplir.

Esta es la pieza central del patrón Adapter: el orquestador (IdentityService)
solo conoce esta interfaz. No sabe -ni le importa- si por debajo hay boto3,
el SDK de Google o Microsoft Graph. Cada implementación absorbe las
particularidades reales de su nube (ver AwsAdapter, GcpAdapter, AzureAdapter).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from app.models.unified import CloudProvider


@dataclass
class AdapterResult:
    """Resultado uniforme de una operación de onboarding/offboarding.

    `before` / `after` son snapshots libres (dict) del estado del recurso
    en la nube nativa, usados tal cual para la fila de Audit — así cada
    Adapter decide qué vale la pena registrar de su propia API.
    """

    success: bool
    provider_ref: Optional[str] = None
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class CloudAdapter(ABC):
    """Interfaz común para gobernar identidades en una nube específica."""

    provider: CloudProvider

    @abstractmethod
    async def onboard(self, *, identity_id: str, display_name: str, role_key: str) -> AdapterResult:
        """Crea (o reutiliza) el principal en la nube y le otorga el rol.

        Debe ser idempotente: llamarlo dos veces con el mismo identity_id
        no debe romper nada ni duplicar recursos.
        """
        raise NotImplementedError

    @abstractmethod
    async def offboard(self, *, identity_id: str, provider_ref: Optional[str]) -> AdapterResult:
        """Revoca el acceso otorgado. Debe ser seguro llamarlo aunque el
        recurso ya no exista (offboarding de algo que nunca se aplicó).
        """
        raise NotImplementedError
