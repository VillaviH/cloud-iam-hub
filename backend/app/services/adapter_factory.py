"""Fábrica de adapters — resuelve el flag CLOUD_IAM_MODE=sandbox|live.

Este es el único punto del código que decide entre adapters reales
(AwsAdapter, GcpAdapter, AzureAdapter) y el MockAdapter. El resto del
sistema (IdentityService, routers) no sabe ni le importa en qué modo
está corriendo — siempre habla contra la interfaz CloudAdapter.
"""

from __future__ import annotations

from functools import lru_cache

from app.adapters.base import CloudAdapter
from app.adapters.mock_adapter import MockAdapter
from app.config import Settings, get_settings
from app.models.unified import CloudProvider


def build_adapters(settings: Settings) -> dict[CloudProvider, CloudAdapter]:
    if settings.cloud_iam_mode == "sandbox":
        return {
            CloudProvider.AWS: MockAdapter(CloudProvider.AWS),
            CloudProvider.GCP: MockAdapter(CloudProvider.GCP),
            CloudProvider.AZURE: MockAdapter(CloudProvider.AZURE),
        }

    # Import diferido: las dependencias de los adapters reales (boto3,
    # google-cloud-*, azure-*) solo se cargan si realmente se necesitan,
    # así el modo sandbox puede correr sin ellas instaladas.
    from app.adapters.aws_adapter import AwsAdapter
    from app.adapters.azure_adapter import AzureAdapter
    from app.adapters.gcp_adapter import GcpAdapter

    return {
        CloudProvider.AWS: AwsAdapter(settings),
        CloudProvider.GCP: GcpAdapter(settings),
        CloudProvider.AZURE: AzureAdapter(settings),
    }


@lru_cache
def get_adapters() -> dict[CloudProvider, CloudAdapter]:
    return build_adapters(get_settings())
