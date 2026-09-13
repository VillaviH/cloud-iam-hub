"""Punto de entrada de la API — cloud-iam-hub.

Correr localmente:
    uvicorn app.main:app --reload --port 8080

Desplegar a Cloud Run:
    gcloud run deploy cloud-iam-hub-backend --source . --region <region>

El modo (sandbox|live) se controla enteramente por la variable de entorno
CLOUD_IAM_MODE (ver app/config.py). Por defecto es "sandbox": correr esta
API sin ningún .env configurado funciona de inmediato, sin credenciales
de ninguna nube, con el MockAdapter y el InMemoryRepository.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import identity

logging.basicConfig(level=logging.INFO)

settings = get_settings()

app = FastAPI(
    title="cloud-iam-hub",
    description="Cerebro en GCP que gobierna identidades en AWS, GCP y Azure — patrón Adapter.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.api_cors_origins.split(",")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(identity.router, tags=["identity"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "mode": settings.cloud_iam_mode}
