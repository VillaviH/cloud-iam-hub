"""MockAdapter — plan B en tarima.

Implementa exactamente la misma interfaz CloudAdapter, pero no hace
ninguna llamada real a ninguna nube: simula onboarding/offboarding en
memoria con una pequeña latencia artificial, para que la demo se vea y
se sienta igual que en modo "live" si la red o las credenciales fallan
justo antes de salir a tarima.

Activado con CLOUD_IAM_MODE=sandbox (ver app/config.py y
app/services/adapter_factory.py).
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional

from app.adapters.base import AdapterResult, CloudAdapter
from app.models.unified import CloudProvider


class MockAdapter(CloudAdapter):
    def __init__(self, provider: CloudProvider) -> None:
        self.provider = provider

    async def onboard(self, *, identity_id: str, display_name: str, role_key: str) -> AdapterResult:
        await asyncio.sleep(random.uniform(0.2, 0.6))
        provider_ref = f"mock:{self.provider.value}:{identity_id}"
        return AdapterResult(
            success=True,
            provider_ref=provider_ref,
            before=None,
            after={
                "provider": self.provider.value,
                "identity_id": identity_id,
                "display_name": display_name,
                "role_key": role_key,
                "mode": "sandbox",
            },
        )

    async def offboard(self, *, identity_id: str, provider_ref: Optional[str]) -> AdapterResult:
        await asyncio.sleep(random.uniform(0.2, 0.6))
        return AdapterResult(
            success=True,
            provider_ref=provider_ref,
            before={"identity_id": identity_id, "mode": "sandbox"},
            after=None,
        )
