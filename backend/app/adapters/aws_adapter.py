"""AwsAdapter — gobierna identidades en AWS IAM.

Lo que este adapter demuestra en vivo (ver docs/IAM_CLOUD_MAPPING.md):

AWS no tiene una API "disable user". El offboarding real es una
composición de pasos: quitar la política adjunta, eliminar el login
profile (si existe) y desactivar/eliminar las access keys. Si además se
usa IAM Identity Center (SSO), ahí sí existe un disable directo a nivel
del store de identidades — pero ese es otro servicio con otro API, y
este adapter no lo cubre (fuera de alcance de la demo).

Todo el acceso de este adapter está acotado por `aws_demo_iam_path`
(típicamente "/cloud-iam-hub-demo/"): el usuario IAM que corre el backend
(ver infra/aws/main.tf -> backend_operator) solo tiene permisos sobre
usuarios bajo ese path, así que aunque el código tuviera un bug, no puede
tocar ningún otro usuario/rol real de la cuenta.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from app.adapters.base import AdapterResult, CloudAdapter
from app.config import Settings
from app.models.unified import CloudProvider

logger = logging.getLogger(__name__)


def _iam_user_name(identity_id: str) -> str:
    # Nombres de usuario IAM no aceptan ciertos caracteres; identity_id
    # ya es alfanumérico + guiones (ver models/unified.py), así que es seguro.
    return f"demo-{identity_id}"


class AwsAdapter(CloudAdapter):
    provider = CloudProvider.AWS

    def __init__(self, settings: Settings, session: Optional[boto3.Session] = None) -> None:
        self._settings = settings
        self._session = session or boto3.Session(region_name=settings.aws_region)
        self._iam = self._session.client("iam")

    async def onboard(self, *, identity_id: str, display_name: str, role_key: str) -> AdapterResult:
        user_name = _iam_user_name(identity_id)
        path = self._settings.aws_demo_iam_path

        try:
            before = self._safe_get_user(user_name)

            self._iam.create_user(
                UserName=user_name,
                Path=path,
                Tags=[
                    {"Key": "project", "Value": "cloud-iam-hub"},
                    {"Key": "identity_id", "Value": identity_id},
                    {"Key": "display_name", "Value": display_name[:255]},
                    {"Key": "role_key", "Value": role_key},
                ],
            )

            if self._settings.aws_demo_target_policy_arn:
                self._iam.attach_user_policy(
                    UserName=user_name,
                    PolicyArn=self._settings.aws_demo_target_policy_arn,
                )

            after = self._safe_get_user(user_name)
            arn = after.get("Arn") if after else None

            return AdapterResult(success=True, provider_ref=arn, before=before, after=after)

        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "EntityAlreadyExists":
                # Idempotencia: si ya existe, tratamos como éxito y seguimos.
                existing = self._safe_get_user(user_name)
                return AdapterResult(
                    success=True,
                    provider_ref=existing.get("Arn") if existing else None,
                    after=existing,
                )
            logger.exception("AwsAdapter.onboard failed for %s", user_name)
            return AdapterResult(success=False, error=str(exc))

    async def offboard(self, *, identity_id: str, provider_ref: Optional[str]) -> AdapterResult:
        user_name = _iam_user_name(identity_id)

        try:
            before = self._safe_get_user(user_name)
            if before is None:
                # Ya no existe: offboarding de algo inexistente se considera éxito.
                return AdapterResult(success=True, before=None, after=None)

            # 1) Desasociar TODAS las policies administradas adjuntas.
            attached = self._iam.list_attached_user_policies(UserName=user_name)
            for policy in attached.get("AttachedPolicies", []):
                self._iam.detach_user_policy(UserName=user_name, PolicyArn=policy["PolicyArn"])

            # 2) Eliminar policies inline, si las hubiera.
            inline = self._iam.list_user_policies(UserName=user_name)
            for policy_name in inline.get("PolicyNames", []):
                self._iam.delete_user_policy(UserName=user_name, PolicyName=policy_name)

            # 3) Eliminar access keys — no hay "disable", solo se puede
            #    inactivar o borrar. Para el offboarding real, se borran.
            keys = self._iam.list_access_keys(UserName=user_name)
            for key in keys.get("AccessKeyMetadata", []):
                self._iam.delete_access_key(UserName=user_name, AccessKeyId=key["AccessKeyId"])

            # 4) Eliminar login profile (acceso a consola), si existe.
            try:
                self._iam.delete_login_profile(UserName=user_name)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
                    raise

            # 5) Finalmente, eliminar el propio usuario.
            self._iam.delete_user(UserName=user_name)

            return AdapterResult(success=True, before=before, after=None)

        except ClientError as exc:
            logger.exception("AwsAdapter.offboard failed for %s", user_name)
            return AdapterResult(success=False, error=str(exc))

    def _safe_get_user(self, user_name: str) -> Optional[dict[str, Any]]:
        try:
            response = self._iam.get_user(UserName=user_name)
            user = response["User"]
            return {
                "UserName": user["UserName"],
                "Arn": user["Arn"],
                "Path": user["Path"],
                "CreateDate": str(user["CreateDate"]),
            }
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "NoSuchEntity":
                return None
            raise
