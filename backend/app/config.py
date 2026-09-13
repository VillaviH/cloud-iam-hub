"""Configuración centralizada del backend.

Todo lo sensible (credenciales, IDs de tenant/proyecto/cuenta) viene de
variables de entorno (.env, gitignored) — nunca hardcodeado en el
repositorio. Ver .env.example para la lista completa de variables.

Incluye un chequeo de seguridad deliberado: `assert_azure_tenant_is_safe()`.
Este proyecto se comparte como repo público y se corre en vivo en un
escenario. El AzureAdapter jamás debe ejecutarse contra un tenant que no
sea el declarado explícitamente como "propio" en AZURE_TENANT_ID. Si el
usuario tiene una sesión de `az login` distinta activa (p. ej. un tenant
corporativo) por accidente, el arranque falla rápido y ruidoso en lugar de
ejecutar cualquier llamada real.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Modo general ---
    # "sandbox": todos los adapters devuelven resultados simulados (mock),
    #            ninguna llamada real sale a ninguna nube. Plan B de demo.
    # "live":    llamadas reales a AWS / GCP / Azure.
    cloud_iam_mode: Literal["sandbox", "live"] = "sandbox"

    # --- Firestore (estado del hub) ---
    gcp_project_id: str = ""
    google_application_credentials: Optional[str] = None  # path a gcp-sa.json

    # --- AWS ---
    aws_region: str = "us-east-1"
    aws_demo_iam_path: str = "/cloud-iam-hub-demo/"
    aws_demo_target_policy_arn: str = ""  # output de infra/aws (demo_target_policy_arn)

    # --- GCP (recurso gobernado: el propio proyecto de Firestore, por simplicidad de demo) ---
    # Email del service account de demo creado por Terraform
    # (infra/gcp/main.tf -> demo_target_principal), sobre el que el
    # GcpAdapter agrega/quita bindings en cada onboarding/offboarding.
    gcp_demo_target_resource_member: str = ""

    # --- Azure ---
    azure_tenant_id: str = ""       # tenant PROPIO esperado (obligatorio en modo live)
    azure_subscription_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    azure_resource_group: str = "rg-cloud-iam-hub-demo"
    # Dominio del tenant propio usado para generar UPNs de demo
    # (ej: "tu-tenant.onmicrosoft.com"). Se define vía .env, nunca hardcodeado.
    azure_upn_domain: str = ""

    # --- API ---
    api_cors_origins: str = "*"
    # Si se define, POST /onboard, POST /offboard y GET /audit exigen el
    # header `X-Api-Key` con este valor. Si se deja vacío, la API queda
    # abierta (aceptable solo en localhost / modo sandbox). Al desplegar
    # a Cloud Run con un frontend público, definir SIEMPRE este valor —
    # ver README, sección de seguridad.
    api_shared_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


class UnsafeAzureTenantError(RuntimeError):
    """Se lanza cuando el tenant de Azure activo no coincide con el esperado.

    Esto protege contra el peor escenario posible en una demo pública:
    ejecutar operaciones de IAM reales contra un directorio corporativo
    por tener una sesión de `az login` distinta abierta por accidente.
    """


def assert_azure_tenant_is_safe(active_tenant_id: str, settings: Settings) -> None:
    if settings.cloud_iam_mode != "live":
        return  # en sandbox nunca se llama a Azure real, no hay riesgo

    if not settings.azure_tenant_id:
        raise UnsafeAzureTenantError(
            "AZURE_TENANT_ID no está configurado. En modo 'live' es obligatorio "
            "declarar explícitamente el tenant propio/personal que se va a usar."
        )

    if active_tenant_id != settings.azure_tenant_id:
        raise UnsafeAzureTenantError(
            "El tenant de Azure activo NO coincide con AZURE_TENANT_ID configurado. "
            "Por seguridad, cloud-iam-hub se niega a ejecutar operaciones de IAM "
            "reales contra un tenant no declarado explícitamente como propio. "
            "Verifica tu sesión con `az account show` antes de reintentar."
        )
