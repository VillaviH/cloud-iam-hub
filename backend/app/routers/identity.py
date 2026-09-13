"""Endpoints de gobierno de identidades: onboarding, offboarding y audit.

Estos son los tres endpoints que se disparan en vivo durante la demo
(ver docs/ARCHITECTURE.md y el guion del diagrama en
diagrams/cloud-iam-hub.drawio):

  POST /onboard   -> crea la Identity + Assignments y ejecuta el fan-out
  POST /offboard  -> revoca en las nubes indicadas (o en todas)
  GET  /audit     -> trazabilidad cross-cloud (por correlation_id o reciente)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.config import get_settings
from app.models.unified import (
    OffboardRequest,
    OffboardResult,
    OnboardRequest,
    OnboardResult,
)
from app.repositories.factory import get_repository
from app.services.adapter_factory import get_adapters
from app.services.identity_service import IdentityService

router = APIRouter()


def _get_service() -> IdentityService:
    return IdentityService(repo=get_repository(), adapters=get_adapters())


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Protege /onboard, /offboard y /audit con un shared secret simple.

    Si API_SHARED_SECRET no está configurado, no se exige nada (útil para
    desarrollo local en sandbox). Al desplegar a Cloud Run con un frontend
    público, define API_SHARED_SECRET y comparte el valor solo con quien
    deba disparar la demo — ver README, sección de seguridad.
    """
    settings = get_settings()
    if not settings.api_shared_secret:
        return
    if x_api_key != settings.api_shared_secret:
        raise HTTPException(status_code=401, detail="X-Api-Key inválido o ausente")


@router.post("/onboard", response_model=OnboardResult, dependencies=[Depends(require_api_key)])
async def onboard(payload: OnboardRequest) -> OnboardResult:
    service = _get_service()
    correlation_id, identity, assignments = await service.onboard(
        display_name=payload.display_name,
        email=payload.email,
        role_key=payload.role_key,
        providers=payload.providers,
    )
    return OnboardResult(correlation_id=correlation_id, identity=identity, assignments=assignments)


@router.post("/offboard", response_model=OffboardResult, dependencies=[Depends(require_api_key)])
async def offboard(payload: OffboardRequest) -> OffboardResult:
    service = _get_service()
    try:
        correlation_id, assignments = await service.offboard(
            identity_id=payload.identity_id,
            providers=payload.providers,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return OffboardResult(
        correlation_id=correlation_id,
        identity_id=payload.identity_id,
        assignments=assignments,
    )


@router.get("/audit", dependencies=[Depends(require_api_key)])
async def get_audit(
    correlation_id: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
):
    repo = get_repository()
    if correlation_id:
        entries = repo.get_audit_for_correlation(correlation_id)
    else:
        entries = repo.get_recent_audit(limit=limit)
    return {"entries": [e.model_dump(mode="json") for e in entries]}
