"""Modelo de datos unificado.

Este es el contrato ÚNICO que ve el resto del hub (API, orquestador,
auditoría). Cada Adapter traduce estas cuatro entidades al lenguaje nativo
de su nube — eso es literalmente el patrón Adapter aplicado a IAM.

Diseño deliberado:
- `Identity` no representa una persona real: representa un principal de
  DEMO, autocontenido y desechable, para que la charla pueda mostrar un
  ciclo de vida completo (crear -> asignar -> auditar -> revocar) sin
  tocar identidades humanas reales.
- `Assignment` es la unidad de trabajo que dispara el fan-out hacia los
  tres adapters: una Identity puede tener un Assignment por proveedor.
- `Audit` es append-only. Nunca se edita ni se borra un registro de audit;
  cada acción (éxito o error) agrega una entrada nueva.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CloudProvider(str, Enum):
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"


class AssignmentStatus(str, Enum):
    PENDING = "pending"       # intención escrita, aún no aplicada
    APPLIED = "applied"       # el adapter confirmó éxito
    FAILED = "failed"         # el adapter reportó un error
    REVOKED = "revoked"       # offboarding aplicado con éxito


class AuditAction(str, Enum):
    ONBOARD = "onboard"
    OFFBOARD = "offboard"


class Identity(BaseModel):
    """Un principal de demo gobernado por el hub.

    No es una identidad humana real: es un registro autocontenido creado
    y destruido dentro del ciclo de vida de la propia demo.
    """

    id: str = Field(default_factory=lambda: f"identity-{uuid4().hex[:12]}")
    display_name: str
    email: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    created_by: str = "cloud-iam-hub-demo"
    metadata: dict[str, Any] = Field(default_factory=dict)


class Role(BaseModel):
    """Rol/permiso conceptual, unificado, que un Adapter traduce a su nube.

    Ej: role_key="viewer" -> AwsAdapter adjunta una IAM Policy de solo
    lectura, GcpAdapter agrega un binding roles/viewer, AzureAdapter crea
    un roleAssignment "Reader".
    """

    key: str
    description: str = ""


class Assignment(BaseModel):
    """La INTENCIÓN: 'esta Identity debe tener este Role en este Provider'.

    Es lo que se escribe primero en Firestore (antes de que ningún Adapter
    haya hecho nada) y lo que dispara el fan-out hacia el adapter correcto.
    """

    id: str = Field(default_factory=lambda: f"assignment-{uuid4().hex[:12]}")
    identity_id: str
    provider: CloudProvider
    role_key: str
    status: AssignmentStatus = AssignmentStatus.PENDING
    provider_ref: Optional[str] = None  # ej: IAM user ARN, service account email, object id
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    error: Optional[str] = None


class AuditEntry(BaseModel):
    """Registro append-only. Una entrada por cada acción de cada Adapter.

    `correlation_id` amarra todas las entradas de un mismo onboarding u
    offboarding (una Identity con 3 Assignments genera 3 AuditEntry con el
    mismo correlation_id), lo cual permite reconstruir la operación
    cross-cloud completa desde un solo query.
    """

    id: str = Field(default_factory=lambda: f"audit-{uuid4().hex[:12]}")
    correlation_id: str
    identity_id: str
    provider: CloudProvider
    action: AuditAction
    actor: str
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    success: bool = True
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=_utcnow)


class OnboardRequest(BaseModel):
    """Payload de entrada de POST /onboard.

    `providers` es opcional: si se omite, el hub onboardea en las 3 nubes
    (AWS + GCP + Azure) a la vez, que es el golpe de efecto de la demo.
    """

    display_name: str
    email: Optional[str] = None
    role_key: str = "viewer"
    providers: Optional[list[CloudProvider]] = None


class OffboardRequest(BaseModel):
    identity_id: str
    providers: Optional[list[CloudProvider]] = None


class OnboardResult(BaseModel):
    correlation_id: str
    identity: Identity
    assignments: list[Assignment]


class OffboardResult(BaseModel):
    correlation_id: str
    identity_id: str
    assignments: list[Assignment]
